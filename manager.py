#!/usr/bin/env python3

import click
import os
import pickle
import platform
import random
import shutil
import subprocess
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
    """
    Run an external system command.
    """
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
            template = '{{:>4}}  {{:<{}}}  {{:>6}}  {{:>5}} ' \
                       ' {{:>6}}  {{}}\n'.format(max_name)
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


def random_contestants(db, number, priority):
    """
    Generate between 2 and 6 random contestants, prioritizing given bots.
    """
    if not number:
        number = random.randint(max(2, len(priority)), min(6, len(db.names())))
    contestants = []

    if priority:
        pool = [x for x in db.names() if x not in priority]
        random.shuffle(pool)
        contestants = priority + pool[:number-len(priority)]
        random.shuffle(contestants)
    else:
        pool = db.names()
        random.shuffle(pool)
        contestants = pool[:number]

    return contestants


def match(db, width, height, contestants, seed=None):
    """
    Runs halite game, parses output, and moves replay file.
    """
    cmd = '{} -q -d "{} {}" '.format(HALITEBIN, width, height)
    cmd += '-s "{}" '.format(seed) if seed else ''
    cmd += ' '.join('"{}"'.format(db.get_command(c)) for c in contestants)
    _, stdout, _ = external(cmd)

    lines = stdout.decode('utf-8').strip().split('\n')[len(contestants):]
    replay_file = lines[0].split(' ')[0]
    ranks = [int(x.split()[1])-1 for x in lines[1:1+len(contestants)]]
    frames = [int(x.split()[2])-1 for x in lines[1:1+len(contestants)]]

    if not platform.system() == 'Windows':
        shutil.move(replay_file, os.path.join(REPLAYDIR, replay_file))

    return ranks, frames, replay_file


def update_rankings(db, contestants, ranks):
    """
    Update rankings to database.
    """
    players = [(db.get_rating(c),) for c in contestants]

    ts = trueskill.TrueSkill(draw_probability=0)
    ratings = ts.rate(players, ranks)
    for i in range(len(contestants)):
        db.set_rating(contestants[i], ratings[i][0])


def run_serial_matches(db, matches, seed=None,
                       dimensions=(None, None), bots=None, priority=None):
    """
    Serially run matches.
    """
    try:
        for _ in range(matches):
            if not all(dimensions):
                d = random.choice(range(20, 51, 5))
                width, height = (d, d)
            else:
                width, height = dimensions
            contestants = random_contestants(db, bots, priority)
            click.echo('MATCH: {} x {}, {}'.format(width, height,
                       ' vs '.join(contestants)))
            ranks, frames, rfile = match(db, width, height, contestants, seed)
            if bots == 1:
                click.echo('RESULT: {} frames'.format(frames[0]))
            else:
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


def run_parallel_matches(db, threads, matches, seed=None,
                         dimensions=(None, None), bots=None, priority=None):
    """
    Run matches in parallel.
    """
    def parallel_worker():
        while True:
            if in_queue.empty():
                break
            else:
                width, height, contestants = in_queue.get()
                click.echo('MATCH: {} x {}, {}'.format(width, height,
                           ' vs '.join(contestants)))
                ranks, _, rfile = match(db, width, height, contestants, seed)
                out_queue.put((contestants, ranks, rfile))

    def drainer(q):
        while True:
            if not q.empty():
                yield q.get_nowait()
            else:
                break

    in_queue = Queue()
    out_queue = Queue()
    for i in range(matches):
        if not all(dimensions):
            d = random.choice(range(20, 51, 5))
            width, height = (d, d)
        else:
            width, height = dimensions
        contestants = random_contestants(db, bots, priority)
        in_queue.put((width, height, contestants))
    processes = [Process(target=parallel_worker)
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
    all the currently stored bots. Matches can be run either serially or in
    parallel.
    """
    ctx.obj = Database('manager.db')


@cli.command()
@click.argument('path', type=click.Path(exists=True))
@click.option('--prefix', '-p', type=str, default='python3',
              help='The command prefix to run the file.')
@click.option('--name', '-n', type=str)
@click.option('--rating', '-r', type=(float, float), default=(25.000, 8.333),
              help='Specify MU and SIGMA for bot(s).')
@click.pass_context
def add(ctx, path, prefix, name, rating):
    """
    Add bot(s) to the manager.

    \b
    PATH is the path to a bot's file or a folder containing multiple bots.
    """
    db = ctx.obj

    def add(db, name, path, rating):
        if name not in db.names():
            db.add(name, '{} {}'.format(prefix, path),
                   rating=trueskill.Rating(*rating))
            click.echo('Added {}'.format(name))
            db.save()
        else:
            click.echo('{} already exists'.format(name))

    if os.path.isdir(path):
        for p in os.listdir(path):
            if 'Bot' in p:
                add(db, os.path.splitext(p)[0], os.path.join(path, p), rating)
    else:
        if not name:
            name = os.path.splitext(os.path.basename(path.rstrip(os.sep)))[0]
        add(db, name, path, rating)


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
@click.option('--seed', '-s', type=int, default=None,
              help='Match seed.')
@click.option('--dimensions', '-d', type=(int, int), default=(None, None),
              help='Dimensions for game.')
@click.option('--number', '-n', type=click.IntRange(1, None), default=None,
              help='Number of bots in game.')
@click.option('--priority', '-p', type=str, multiple=True,
              help='Name of a bot to ensure is in the game.')
@click.pass_context
def run(ctx, matches, threads, seed, dimensions, number, priority):
    """
    Run matches.

    If this command receives a keyboard interrupt (SIGTERM) then the matches
    that have been completed will update the rankings before the program exits.
    """
    db = ctx.obj

    if priority and not all(x in db.names() for x in priority):
        click.echo('Bot not found')
    elif len(db.names()) >= 1:
        if threads == 1 or matches == 1:
            run_serial_matches(db, matches, seed, dimensions,
                               number, list(priority))
        else:
            run_parallel_matches(db, threads, matches, seed, dimensions,
                                 number, list(priority))
        db.save()
        if (number and number > 1) or not number:
            click.echo(db)
    else:
        click.echo('Not enough bots to play a game.')
        click.echo('Use the \'add\' command to add bots.')


@cli.command()
@click.option('--reset-all', '-r', is_flag=True,
              help='Reset ratings for all bots.')
@click.pass_context
def ls(ctx, reset_all):
    """
    Display the rankings.
    """
    db = ctx.obj

    if reset_all:
        for name in db.names():
            db.reset_rating(name)
        db.save()
    click.echo(db)


if __name__ == '__main__':
    cli()
