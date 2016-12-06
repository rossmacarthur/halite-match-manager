#!/usr/bin/env python3

import click
import os
import pickle
import platform
import random
import shutil
import subprocess
import statistics
import trueskill
from multiprocessing import Process, Queue, cpu_count


if platform.system() == 'Windows':
    HALITEBIN = '.\\halite.exe'
else:
    HALITEBIN = './halite'
if not os.path.exists(HALITEBIN):
    raise Exception('Could not find the halite binary.')
REPLAYDIR = 'replays'
if not os.path.exists(REPLAYDIR):
    os.makedirs(REPLAYDIR)
CPUs = cpu_count()


def external(cmd):
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, shell=True)
    stdout, stderr = proc.communicate()
    return proc.returncode, stdout, stderr


class Database:
    def __init__(self, filename):
        self.filename = filename
        if os.path.isfile(filename):
            self.db = pickle.load(open(self.filename, 'rb'))
        else:
            self.db = {}

    def __str__(self):
        if self.db:
            rows = []
            for name in self.db:
                rows.append((name,
                             '{:.2f}'.format(self.db[name]['rating'].mu),
                             '{:.2f}'.format(self.db[name]['rating'].sigma),
                             self.db[name]['played'],
                             self.db[name]['command']))
            rows = sorted(rows, key=lambda x: x[1], reverse=True)
            max_name = max([4]+[len(x[0]) for x in rows])
            template = '{{:>4}}  {{:<{}}}  {{:>7}}  {{:>5}} ' \
                       ' {{:>7}}  {{}}\n'.format(max_name)
            s = template.format('Rank', 'Name', 'Rating',
                                'Sigma', 'Played', 'Command')
            for i in range(len(rows)):
                s += template.format(i+1, *rows[i])
            return 79*'=' + '\n' + s + 79*'='
        else:
            return 'Database empty'

    def save(self):
        with open(self.filename, 'wb') as output_file:
            pickle.dump(self.db, output_file, -1)

    def names(self):
        return list(self.db)

    def add(self, name, command, rating=trueskill.Rating(), played=0):
        self.db[name] = {'command': command,
                         'rating': rating,
                         'played': played}

    def rm(self, name):
        del self.db[name]

    def get_command(self, name):
        return self.db[name]['command']

    def set_rating(self, name, rating):
        self.db[name]['rating'] = rating
        self.db[name]['played'] += 1

    def get_rating(self, name):
        return self.db[name]['rating']

    def reset_rating(self, name):
        self.db[name]['rating'] = trueskill.Rating()
        self.db[name]['played'] = 0


def random_contestants(db):
    """
    Generate between 2 and 6 random contestants, prioritizing high sigma bots.
    """
    number = random.randint(2, min(6, len(db.names())))
    contestants = []

    pool = list(db.names())
    non_high = number
    sigmadev = statistics.stdev(db.get_rating(n).sigma for n in db.names())
    sigmamean = statistics.mean(db.get_rating(n).sigma for n in db.names())
    for n in db.names():
        if db.get_rating(n).sigma > sigmamean + 2*sigmadev:
            contestants.append(n)
            pool.remove(n)
            non_high -= 1
    random.shuffle(pool)
    contestants.extend(pool[:non_high])

    return contestants


def random_dimensions():
    """
    Generate random dimensions (width, height).
    """
    d = random.choice(range(20, 51, 5))
    return d, d


def match(db, width, height, contestants):
    """
    Runs halite game, parses output, and moves replay file.
    """
    cmd = '{} -q -d "{} {}" '.format(HALITEBIN, width, height)
    cmd += ' '.join('"{}"'.format(db.get_command(c)) for c in contestants)
    _, stdout, _ = external(cmd)

    lines = stdout.decode('utf-8').strip().split('\n')[len(contestants):]
    replay_file = lines[0].split(' ')[0]
    ranks = [int(x.split()[1])-1 for x in lines[1:1+len(contestants)]]

    if not platform.system() == 'Windows':
        shutil.move(replay_file, os.path.join(REPLAYDIR, replay_file))

    return ranks, replay_file


def update_rankings(db, contestants, ranks):
    """
    Update rankings to database.
    """
    players = [(db.get_rating(c),) for c in contestants]

    ts = trueskill.TrueSkill(draw_probability=0)
    ratings = ts.rate(players, ranks)
    for i in range(len(contestants)):
        db.set_rating(contestants[i], ratings[i][0])


def run_serial_matches(db, matches):
    try:
        for _ in range(matches):
            width, height = random_dimensions()
            contestants = random_contestants(db)
            click.echo('MATCH: {} x {}, {}'.format(width, height,
                       ' vs '.join(contestants)))
            ranks, rfile = match(db, width, height, contestants)
            update_rankings(db, contestants, ranks)
            d = dict(zip(contestants, ranks))
            contestants.sort(key=d.get)

            click.echo('RESULT: ' +
                       ' '.join(['  #{} {:<}'.format(i+1, contestants[i])
                                 for i in range(len(contestants))]))
            if platform.system() == 'Windows':
                click.echo('Replay: {}'.format(rfile.lower()))
            else:
                click.echo('Replay: {}'.format(os.path.join(REPLAYDIR, rfile)))
            click.echo()
    except KeyboardInterrupt:
        click.echo()


def parallel_worker(db, in_queue, out_queue):
    while True:
        if in_queue.empty():
            break
        else:
            width, height, contestants = in_queue.get()
            click.echo('MATCH: {} x {}, {}'.format(width, height,
                       ' vs '.join(contestants)))
            ranks, replay_file = match(db, width, height, contestants)
            out_queue.put((contestants, ranks, replay_file))


def run_parallel_matches(db, matches, threads):

    def drainer(q):
        while True:
            if not q.empty():
                yield q.get_nowait()
            else:
                break

    in_queue = Queue()
    out_queue = Queue()
    for i in range(matches):
        width, height = random_dimensions()
        contestants = random_contestants(db)
        in_queue.put((width, height, contestants))
    processes = [Process(target=parallel_worker,
                         args=(db, in_queue, out_queue))
                 for _ in range(threads)]
    click.echo('Spawning {} workers\n'.format(threads))
    for p in processes:
        p.start()

    try:
        for p in processes:
            p.join()
            p.terminate()
    except KeyboardInterrupt:
        for p in processes:
            p.terminate()
    finally:
        count = 0
        for contestants, ranks, replay_file in drainer(out_queue):
            count += 1
            update_rankings(db, contestants, ranks)
        click.echo('\nUpdated rankings using {} match results\n'.format(count))


@click.group(context_settings=dict(help_option_names=['-h', '--help']))
@click.pass_context
def cli(ctx):
    """
    Utility to run batch matches between Halite bots. A unique name, rating,
    number of matches played, and the command to run the bot, are stored to a
    file. Bots are rated using the TrueSkill rating system. Games are run on
    all the currently stored bots with recently added bots (high sigma)
    prioritized. Matches can be run either serially or in parallel.
    """
    ctx.obj = Database('manager.db')


@cli.command()
@click.argument('name')
@click.argument('command')
@click.option('--rating', type=(float, float), default=(25.000, 8.333),
              help='Specify MU and SIGMA for bot.')
@click.pass_context
def add(ctx, name, command, rating):
    """
    Add bot to the manager.

    \b
    NAME is a unique name for the bot e.g. "MyBot"
    COMMAND is the command to run the bot e.g. "python3 bots/MyBot.py"
    """
    db = ctx.obj

    if name not in db.names():
        db.add(name, command, rating=trueskill.Rating(*rating))
        db.save()
        click.echo('New bot added!')
    else:
        click.echo('Bot with that name already exists')


@cli.command()
@click.argument('name', nargs=-1)
@click.pass_context
def rm(ctx, name):
    """
    Remove bot(s) from manager.

    NAME is the unique name of the bot to remove.
    """
    db = ctx.obj

    for n in name:
        if n in db.names():
            db.rm(n)
            db.save()
            click.echo('Removed {}'.format(n))
        else:
            click.echo('{} not found'.format(n))


@cli.command()
@click.option('--matches', '-m', type=click.IntRange(1, None), default=1,
              help='Number of matches to run.')
@click.option('--threads', '-t', type=click.IntRange(1, None), default=CPUs,
              help='Number of threads to use. Default {}.'.format(CPUs))
@click.pass_context
def run(ctx, matches, threads):
    """
    Run matches.

    If this command receives a keyboard interrupt (SIGTERM) then the matches
    that have been completed will update the rankings before the program exits.
    """
    db = ctx.obj

    if threads == 1 or matches == 1:
        run_serial_matches(db, matches)
    else:
        run_parallel_matches(db, matches, threads)
    db.save()
    click.echo(db)


@cli.command()
@click.option('--reset', '-n', is_flag=True,
              help='Reset all ratings.')
@click.pass_context
def rankings(ctx, reset):
    """
    Display the rankings.
    """
    db = ctx.obj

    if reset:
        for name in db.names():
            db.reset_rating(name)
        db.save()
    click.echo(db)


if __name__ == '__main__':
    cli()
