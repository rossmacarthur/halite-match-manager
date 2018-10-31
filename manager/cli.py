import os
import time
from multiprocessing import cpu_count
from multiprocessing.dummy import Pool

import click
import tabulate
import trueskill

from .core import Bot, Manager


@click.group(context_settings={'help_option_names': ['-h', '--help']})
@click.option('--path', '-p', default='manager.json', help='The path to the manager storage file.')
@click.pass_context
def cli(ctx, path):
    """
    Halite match manager!

    A utility to run batch matches between Halite bots. A unique name, rating,
    number of matches played, and the command to run the bot, are stored to a
    file. Bots are rated using the TrueSkill rating system. Games are run on
    all the currently stored bots. Matches can be run either serially or in
    parallel.
    """
    try:
        manager = Manager.read(path)
    except OSError:
        manager = Manager.new(path)

    ctx.obj = manager


@cli.command('reset')
@click.option('--name', '-n', help='The unique name for the bot to reset.')
@click.pass_obj
def reset(manager, name):
    """
    Reset all bot ratings and clear all games.
    """
    if name:
        bot = manager.bots[name]
        new_games = [
            g for g in manager.games
            if all(c not in manager.bots for c in g.match.contestants)
        ]
        click.confirm('This will reset the rating for bot {!r} and delete {} games. Continue?'
                      .format(bot.name, len(manager.games) - len(new_games)), abort=True)
        bot.reset()
        manager.games = new_games
        click.echo('Bot {!r} reset.'.format(bot.name))
    else:
        click.confirm('This will reset all bot ratings and remove all games. Continue?', abort=True)
        manager.reset()
        click.echo('All bots reset and games removed.')

    manager.save()

@cli.command('add')
@click.option('--name', '-n', help='A unique name for the bot.')
@click.option('--command', '-c', help='The command to execute the bot.', required=True)
@click.option('--rating', '-r', nargs=2, type=float, help='The initial rating for the bot.')
@click.pass_obj
def add(manager, name, command, rating):
    """
    Add a new bot to the manager.
    """
    if name is None:
        for p in command.split():
            name = os.path.basename(p)
            break
        else:
            raise click.ClickException('Unable to determine name for bot from command.')

    if rating:
        rating = trueskill.Rating(*rating)
    else:
        rating = None

    bot = Bot(name=name, command=command, rating=rating)
    click.confirm('Add new bot {!r} with name {!r}?'.format(command, name), abort=True)
    manager.add_bot(bot)
    manager.save()


@cli.command('rm')
@click.option('--name', '-n', help='The unique name for the bot to remove.')
@click.pass_obj
def rm(manager, name):
    """
    Remove a bot from the manager.
    """
    if name:
        del manager.bots[name]
        click.echo('Removed bot {!r}'.format(name))
    else:
        click.confirm('This will remove all bots and games. Continue?', abort=True)
        manager.reset()
        manager.bots = {}
        click.echo('Removed all bots')

    manager.save()


@cli.command('run')
@click.option('--quiet', '-q', is_flag=True,
              help='Whether to output each game information.')
@click.option('--matches', '-m', type=click.IntRange(1, None), default=1,
              help='The number of matches to run.')
@click.option('--threads', '-t', type=click.IntRange(1, None), default=cpu_count(),
              help='The number of threads to use.', show_default=True)
@click.option('--prioritize', '-p', multiple=True,
              help='The name of a bot to ensure is a contestant.')
@click.option('--count', '-c', type=click.IntRange(1, 8),
              help='The number of bots in each game.')
@click.option('--dimension', '-d', type=click.IntRange(32, 68),
              help='The map dimension for the games.')
@click.option('--seed', '-s', type=int,
              help='The map seed.')
@click.pass_obj
def run(manager, quiet, matches, threads, prioritize, count, dimension, seed):
    """
    Run bots against each other.
    """
    matches_to_run = manager.generate_matches(
        matches,
        count=count,
        prioritize=prioritize,
        dimension=dimension,
        seed=seed
    )

    def worker(match):
        nonlocal completed
        game = match.run()
        if not quiet:
            click.echo('=' * 80 + '\n' + str(game))
        completed += 1
        manager.add_game(game)
        return game

    try:
        completed = 0
        start = time.time()
        pool = Pool(threads)
        pool.map(worker, matches_to_run)
        if not quiet:
            click.echo('=' * 80)

        end = time.time() - start

    except KeyboardInterrupt:
        click.echo()
        if not quiet:
            click.echo('=' * 80)
        end = time.time() - start
        pool.terminate()
        if completed > 0:
            click.confirm('Interrupted! Update bot rankings with results for {} games?'
                          .format(completed), abort=True)

    click.echo('Ran {} games in {}m {}s.'
               .format(completed, round(end // 60 % 60), round(end % 60)))
    manager.save()


@cli.command('bots')
@click.pass_obj
def bots(manager):
    """
    List the bots and their ratings.
    """
    table = []
    bots = sorted(manager.bots.values(), key=lambda b: (b.rating, b.name), reverse=True)
    for bot in bots:
        win_rate = 100 * (bot.won / bot.played) if bot.played > 0 else None
        table.append((
            bot.name, bot.command, bot.played, win_rate,
            'μ={:.3f} σ={:.3f}'.format(bot.rating.mu, bot.rating.sigma)
        ))

    if not table:
        click.echo('No bots have been added yet!')
    else:
        click.echo(tabulate.tabulate(
            table,
            headers=('Name', 'Command', 'Played', 'Win %', 'Rating'),
            showindex=range(1, len(bots) + 1),
            floatfmt='.1f',
            tablefmt='psql',
        ))
