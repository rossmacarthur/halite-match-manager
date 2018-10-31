# Halite match manager

A Python 3 utility to run batch matches between Halite bots. Bots are rated
using the [TrueSkill](http://trueskill.org/) rating system and the rankings and
all other relevant information about bots are stored to a file. Matches will run
in parallel unless otherwise specified.

### Install

```
git clone git@github.com:rossmacarthur/halite-match-manager.git
cd halite-match-manager
```

It is recommended that you set a virtualenv here. Once you've done that you can
simply

```
pip install .
```

This will install the `halite-cli` CLI tool.

### Usage

Add bots to the manager using the `add` command:
```
halite-cli add --name "MyBotv1" --command "python3 bots/MyBotv1.py"
```

Games can be run on all bots stored in the manager using the `run` command:
```
halite-cli run --matches 10 --threads 4
```

This will run 10 games using 4 worker threads.

The rankings that are stored in the file can be viewed using:

```
halite-cli bots
```

You can use the `--help` option to get more information on commands and options.

```
halite-cli --help
halite-cli <command> --help
```
