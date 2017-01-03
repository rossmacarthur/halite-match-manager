# Halite match manager

A Python 3 utility to run batch matches between bots. Bots are rated using the [TrueSkill](http://trueskill.org/) rating system and the rankings and all other relevant information about bots are stored to a file. Matches will run in parallel unless otherwise specified. 


### Setup

Install required Python packages:
```
pip3 install click trueskill
```
Add the halite environment binary to the same directory as manager.py (or change the global variable HALITEBIN at the top of manager.py).


### Usage

Add bots to the manager using the `add` command:
```
$ ./manager.py add "bots/MyBot.py"
```
An initial rating will be set and all information stored to a file.

Games can be run on all bots stored in the manager using the `run` command:
```
$ ./manager.py run --matches 10 --threads 4
```
This will run 10 games using 4 worker threads. 

At any time the rankings that are stored in the file can be viewed using:

```
$ ./manager.py ls
```

You can use the `--help` option to get more information on commands and options.
