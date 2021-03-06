'''
General management functions for salt, tools like seeing what hosts are up
and what hosts are down
'''

import salt.cli.key
import salt.client


def down():
    '''
    Print a list of all the down or unresponsive salt minions
    '''
    client = salt.client.LocalClient(__opts__['conf_file'])
    key = salt.cli.key.Key(__opts__)
    minions = client.cmd('*', 'test.ping', timeout=1)
    keys = key._keys('acc')

    for minion in sorted(keys - set(minions.keys())):
        print minion


def up():
    '''
    Print a list of all of the minions that are up
    '''
    client = salt.client.LocalClient(__opts__['conf_file'])
    minions = client.cmd('*', 'test.ping', timeout=1)

    for minion in sorted(minions):
        print minion
