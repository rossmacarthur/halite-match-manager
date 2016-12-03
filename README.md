# Halite match manager

A Python 3 utility to run batch matches between bots. Bots are rated using the [TrueSkill](http://trueskill.org/) rating system.


### Setup

Install required Python packages:
```
pip3 install click trueskill
```
Add the halite environment binary to the same directory as manager.py (or change the global variable HALITEBIN at the top of manager.py).


### Usage

```
$ ./manager.py --help
Usage: manager.py [OPTIONS] COMMAND [ARGS]...

  Utility to run batch matches between Halite bots. Bots are rated using the
  TrueSkill rating system.

Options:
  -h, --help  Show this message and exit.

Commands:
  add       Add bot to the manager.
  rankings  Display the rankings.
  rm        Remove bot(s) from manager.
  run       Run some games.
```

You can add as many bots as you want. High sigma (recently added) bots are prioritized when randomizing games. If you don't supply a number of games for the `run` command then it will run until a keyboard interrupt.


### Simple example

Add a couple of bots to the manager using the add command.
```
$ ./manager.py add "MyBot" "python3 bots/MyBot.py"
$ ./manager.py add "ImproveBot" "python3 bots/ImproveBot.py"
```

Run a batch of 10 random games
```
$ ./manager.py run -n 10
```

View the rankings afterwards
```
$ ./manager.py rankings
=====================================================================
Rank  Name         Rating  Sigma  Games  Command
   1  MyBot         34.31   4.99     10  python3 bots/MyBot.py
   2  ImproveBot    15.69   4.99     10  python3 bots/ImproveBot.py
=====================================================================
```

