from setuptools import find_packages, setup


install_requires = [
    'click',
    'tabulate',
    'trueskill'
]

entry_points = {
    'console_scripts': [
        'halite-cli=manager.cli:cli',
    ]
}

setup(
    name='halite-match-manager',
    packages=find_packages(),
    version='0.1.0',
    install_requires=install_requires,
    entry_points=entry_points,
    python_requires='>=3.4',
    description='Halite match manager',
    author='Ross MacArthur',
    author_email='macarthur.ross@gmail.com',
)
