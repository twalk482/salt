'''
Module for finding installed software on linux systems
'''
try:
    import logging
    import rpm
except ImportError:
    #doing this to get to Windows logic
    pass

log = logging.getLogger(__name__)

def __virtual__():
    '''
    Only work on systems which default to systemd
    '''
    # Disable on these platforms, specific service modules exist:
    disable = [
               'Scientific',
               'Gentoo',
               'Ubuntu',
               'FreeBSD',
               'Windows',
              ]
    if __grains__['os'] in disable:
        return False
    return 'software'

def list():
    '''
    returns a dict with rpm software details
    CLI Example::
        salt '*' software.list
    '''
    return get_software()
    

def find(pattern):
    '''
    returns a dict with specific items of interest
    '''
    return search_software(pattern)

def search_software(target):
    """
    Return a dict of applications in rpm that match a target string
    """
    search_results = {}
    rpm_software = get_software()
    for key, value in rpm_software.iteritems():
        if target.lower() in key.lower():
            prd_name = value['name']
            prd_details = value
            search_results[prd_name] = prd_details
    return search_results
    
def get_software():
    """
    Return a dict of applications in rpm
    """
    fnull = open('/dev/null', 'w')
    nameglob = "*"
    software = {}
    tran_set = rpm.TransactionSet()
    db_match = tran_set.dbMatch()
    db_match.pattern('name', rpm.RPMMIRE_GLOB, nameglob)
    for match in db_match:
        software[match['name']] = {'name': match['name'],
                                 'version': match['version'],
                                 'release': match['release'],
                                 'arch': match['arch']}
    return software
