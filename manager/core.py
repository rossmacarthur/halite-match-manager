import json
import os
import platform
import random
import secrets
import subprocess

import trueskill
from serde import Choice, Dict, InstanceField, Int, List, Model, ModelField, Str


if platform.system() == 'Windows':
    HALITEBIN = '.\\halite.exe'
else:
    HALITEBIN = './halite'

if not os.path.exists(HALITEBIN):
    raise RuntimeError('Could not find the halite binary.')


class Rating(InstanceField):

    def __init__(self, **kwargs):
        super().__init__(trueskill.Rating, **kwargs)

    def serialize(self, value):
        return {'mu': value.mu, 'sigma': value.sigma}

    def deserialize(self, value):
        return trueskill.Rating(mu=value['mu'], sigma=value['sigma'])


class Bot(Model):
    # The name of the Bot, this must be unique.
    name = Str()
    # The command to run the Bot.
    command = Str()
    # The Bot's rating.
    rating = Rating(default=trueskill.Rating(mu=25.000, sigma=8.333))
    # The number of Games this Bot has played.
    played = Int(required=False, default=0)
    # The number of Games this Bot has won.
    won = Int(required=False, default=0)

    def reset(self):
        self.rating = self.__fields__.rating.default
        self.played = self.__fields__.played.default
        self.won = self.__fields__.won.default


class Map(Model):
    # The Map width.
    width = Int(min=32, max=64)
    # The Map height.
    height = Int(min=32, max=64)
    # The Map seed.
    seed = Int(required=False)
    # The Map generator algorithm.
    generator = Choice(['basic', 'blur_tile', 'fractal'], required=False)

    @classmethod
    def new(cls, dimension=None, seed=None):
        """
        Construct a new Map with randomly generated dimensions.
        """
        if dimension is None:
            dimension = random.choice([32, 40, 48, 56, 64])

        return Map(width=dimension, height=dimension, seed=seed)

    def __str__(self):
        """
        Display the Map nicely.

        Returns:
            str: the nice string representation.
        """
        return 'Map: {}x{}, seed={}, generator={}'.format(
            self.width, self.height, self.seed, self.generator
        )


class Result(Model):
    # The Bot scores.
    scores = Dict(str, Dict(str, int))
    # Whether to Bots were terminated.
    terminated = Dict(str, bool)

    def ranked(self):
        return zip(*[(name, score['rank']) for name, score in self.scores.items()])

    def __str__(self):
        """
        Display the Result nicely.

        Returns:
            str: the nice string representation.
        """
        scores = sorted(self.scores.items(), key=lambda x: x[1]['rank'])
        ranks = ['{}. {} ({} halite)'.format(score['rank'], name, score['score'])
                 for name, score in scores]
        return 'Result: \n  ' + '\n  '.join(ranks)


class Match(Model):
    # The contestant names.
    contestants = List(str)
    # The Map for this Match.
    map = ModelField(Map)

    def __str__(self):
        """
        Display the Match nicely.

        Returns:
            str: the nice string representation.
        """
        return 'Match:\n  Contestants: {}\n  {}'.format(
            ', '.join(sorted(self.contestants, reverse=True)), self.map
        )

    def run_command(self):
        """
        Generate the run command for this Match.

        Returns:
            list: the subprocess command.
        """
        command = [
            HALITEBIN,
            '--replay-directory', 'replays/',
            '--no-logs',
            '--results-as-json',
            '--width', str(self.map.width),
            '--height', str(self.map.height)
        ]

        if self.map.seed:
            command.extend(['--seed', str(self.map.seed)])

        if self.map.generator:
            command.extend(['--map-type', self.map.generator])

        for i in self.contestants:
            command.append(self._manager.bots[i].command)

        return command

    def run(self):
        """
        Run the Halite game.

        Returns:
            Game: a completed game for this Match.
        """
        result = subprocess.run(self.run_command(), stdout=subprocess.PIPE, check=True)
        result = json.loads(result.stdout)

        self.map.seed = result['map_seed']
        self.map.generator = result['map_generator']

        stats = result['stats']
        terminated = result['terminated']

        return Game(
            match=self,
            result=Result(
                scores={
                    self.contestants[int(k)]: v
                    for k, v in stats.items()
                },
                terminated={
                    self.contestants[int(k)]: v
                    for k, v in terminated.items()
                }
            )
        )


class Game(Model):
    # The Game Match up.
    match = ModelField(Match)
    # The Result of the Match
    result = ModelField(Result)

    def __str__(self):
        return '{}\n{}'.format(self.match, self.result)


class Manager(Model):
    # All configured Bots.
    bots = Dict(str, Bot, default=lambda: {})
    # All Games.
    games = List(Game, default=lambda: [])

    @classmethod
    def new(cls, path):
        """
        Create a new Manager.

        Args:
            path (str): the path location to store this Manager.

        Returns:
            Manager: a new Manager instance.
        """
        manager = cls()
        manager._path
        return manager

    def reset(self):
        """
        Reset all Bot ratings and clear all games.
        """
        self.games = []

        for bot in self.bots.values():
            bot.reset()

    def add_bot(self, bot):
        """
        Add a Bot to the Manager.

        Args:
            bot (Bot): the Bot to add to the manager.
        """
        if bot.name in self.bots:
            raise KeyError('bot with name {!r} already exists'.format(bot.name))

        self.bots[bot.name] = bot
        self.validate()

    def add_game(self, game):
        """
        Add a Game to the Manager, and update the Bot rankings.

        Args:
            game (Game): the Game to add to the manager.
        """
        ts = trueskill.TrueSkill(draw_probability=0)
        names, ranks = game.result.ranked()
        players = [[self.bots[name].rating] for name in names]
        new_ratings = ts.rate(players, ranks)

        for i, name in enumerate(names):
            self.bots[name].rating = new_ratings[i][0]
            self.bots[name].played += 1

            if ranks[i] == 1:
                self.bots[name].won += 1

        self.games.append(game)
        self.validate()

    def generate_contestants(self, count=None, prioritize=None):
        """
        Generate contestants from the stored Bots.

        Args:
            count (int): the number of Bot names to generate.
            prioritize (list): a list of Bot names to attempt to include in the
                contestants.

        Returns:
            list: a list of Bot names.
        """
        if count is None:
            count = random.choice([2, 4])

        if prioritize:
            pool = [name for name in self.bots.keys() if name not in prioritize]
            random.shuffle(pool)
            pool = list(prioritize) + pool[:max(0, count - len(prioritize))]
            random.shuffle(pool)
        else:
            pool = list(self.bots.keys())
            random.shuffle(pool)

        return pool[:count]

    def generate_match(self, contestants=None, map=None):
        """
        Generate a Match.

        Args:
            contestants (list): a list of Bot names.
            map (Map): the map for this Match.

        Returns:
            Match: the generated Match.
        """
        if contestants is None:
            contestants = self.generate_contestants()

        if map is None:
            map = Map.new()

        match = Match(contestants=contestants, map=map)
        match._manager = self

        return match

    def generate_matches(self, n, count=None, prioritize=None, dimension=None, seed=None):
        """
        Bulk generate Matches based on the given criteria.

        This method also generates the seed. This is because the halite binary
        uses the number of seconds from the Unix epoch as the seed, so we could
        potentially get multiple games with the same map.

        Args:
            n (int): the number of matches to generate.
            count (int): the number of contestants in each Match.
            prioritize (list): Bot names to include in the contestants.
            dimension (int): the Map dimension.
            seed (int): the Map seed.

        Returns:
            list: a list of generate Matches.
        """
        matches = []

        for _ in range(n):
            contestants = self.generate_contestants(prioritize=prioritize, count=count)
            map = Map.new(
                dimension=dimension,
                seed=secrets.randbelow(2**31 - 1) if seed is None else seed
            )
            match = self.generate_match(contestants=contestants, map=map)
            matches.append(match)

        return matches

    @classmethod
    def read(cls, path):
        """
        Read the Manager from the given path.

        Args:
            path (str): the path to the file.

        Returns:
            Manager: the loaded Manager.
        """
        with open(path, 'r') as f:
            manager = Manager.from_json(f.read())

        manager._path = path

        return manager

    def save(self):
        """
        Save the Manager to file.
        """
        self.validate()

        with open(self._path, 'w') as f:
            f.write(self.to_json(indent=2))
