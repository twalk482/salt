'''
Module for finding installed software on Windows systems
'''
try:
    import pythoncom
    import win32com.client
    import win32api
    import win32con
    is_windows = True
except ImportError:
    is_windows = False

def __virtual__():
    '''
    Only works on Windows systems
    '''
    if not is_windows:
        return False
    return 'pkg'

def list_pkgs(*args):
    '''
        List the packages currently installed in a dict::
    
            {'<package_name>': '<version>'}
    
        CLI Example::
    
            salt '*' pkg.list_pkgs
    '''
    pythoncom.CoInitialize()
    if len(args) == 0:
        pkgs = dict(
                   __get_reg_software().items() + 
                   __get_msi_software().items())
    else:
        # get package version for each package in *args
        pkgs = {}
        for arg in args:
            pkgs.update(__search_software(arg))
    pythoncom.CoUninitialize()
    return pkgs

def __search_software(target):
    '''
    This searches the msi product databases for name matches
    of the list of target products, it will return a dict with
    values added to the list passed in
    '''
    search_results = {}
    software = dict(
                    __get_reg_software().items() + 
                    __get_msi_software().items())
    for key, value in software.iteritems():
        if key is not None:
            if target.lower() in key.lower():
                search_results[key] = value
    return search_results

def __get_msi_software():
    '''
    This searches the msi product databases and returns a dict keyed
    on the product name and all the product properties in another dict
    '''
    win32_products = {}
    this_computer = "."
    wmi_service = win32com.client.Dispatch("WbemScripting.SWbemLocator")
    swbem_services = wmi_service.ConnectServer(this_computer,"root\cimv2")
    products = swbem_services.ExecQuery("Select * from Win32_Product")
    for product in products:
        prd_name = product.Name.encode('ascii', 'ignore')
        prd_ver = product.Version.encode('ascii', 'ignore')
        win32_products[prd_name] = prd_ver
    return win32_products

def __get_reg_software():
    '''
    This searches the uninstall keys in the registry to find
    a match in the sub keys, it will return a dict with the
    display name as the key and the version as the value
    '''
    reg_software = {}
    #This is a list of default OS reg entries that don't seem to be installed
    #software and no version information exists on any of these items
    ignore_list = ['AddressBook',
                   'Connection Manager',
                   'DirectDrawEx',
                   'Fontcore',
                   'IE40',
                   'IE4Data',
                   'IE5BAKEX',
                   'IEData',
                   'MobileOptionPack',
                   'SchedulingAgent',
                   'WIC'
                   ]
    #attempt to corral the wild west of the multiple ways to install 
    #software in windows
    reg_entries = dict(__get_user_keys().items() + 
                       __get_machine_keys().items())
    for reg_hive, reg_keys in reg_entries.iteritems():
        for reg_key in reg_keys:
            try:
                reg_handle = win32api.RegOpenKeyEx(
                                reg_hive,
                                reg_key,
                                0,
                                win32con.KEY_READ)
            except:
                pass
                #Unsinstall key may not exist for all users
            for name, num, blank, time in win32api.RegEnumKeyEx(reg_handle):
                if name[0] == '{':
                    break
                prd_uninst_key = "\\".join([reg_key, name])
                #These reg values aren't guaranteed to exist
                prd_name = __get_reg_value(
                    reg_hive,
                    prd_uninst_key,
                    "DisplayName")
                prd_ver = __get_reg_value(
                    reg_hive,
                    prd_uninst_key,
                    "DisplayVersion")
                if not name in ignore_list:
                    reg_software[prd_name] = prd_ver
    return reg_software

def __get_machine_keys():
    '''
    This will return the hive 'const' value and some registry keys where 
    installed software information has been known to exist for the 
    HKEY_LOCAL_MACHINE hive
    '''
    machine_hive_and_keys = {}
    machine_keys = [
        "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall",
        "Software\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall",
        ]
    machine_hive = win32con.HKEY_LOCAL_MACHINE
    machine_hive_and_keys[machine_hive] = machine_keys
    return machine_hive_and_keys

def __get_user_keys():
    '''
    This will return the hive 'const' value and some registry keys where 
    installed software information has been known to exist for the 
    HKEY_USERS hive
    '''
    user_hive_and_keys = {}
    user_keys = []
    users_hive = win32con.HKEY_USERS
    #skip some built in and default users since software information in these
    #keys is limited
    skip_users = ['.DEFAULT',
                  'S-1-5-18',
                  'S-1-5-19',
                  'S-1-5-20']
    sw_uninst_key = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
    reg_handle = win32api.RegOpenKeyEx(
                    users_hive,
                    '',
                    0,
                    win32con.KEY_READ)
    for name, num, blank, time in win32api.RegEnumKeyEx(reg_handle):
        #this is some identical key of a sid that contains some software names
        # but no detailed information about the software installed for that user
        if '_Classes' in name:
            break
        if name not in skip_users:
            usr_sw_uninst_key = "\\".join([name, sw_uninst_key])
            user_keys.append(usr_sw_uninst_key)
    user_hive_and_keys[users_hive] = user_keys
    return user_hive_and_keys

def __get_reg_value(reg_hive, reg_key, value_name=''):
    '''
    Read one value from Windows registry.
    If 'name' is empty string, reads default value.
    '''
    value_data = ''
    try:
        key_handle = win32api.RegOpenKeyEx(
            reg_hive, reg_key, 0, win32con.KEY_ALL_ACCESS)
        value_data, value_type = win32api.RegQueryValueEx(key_handle, value_name)
        win32api.RegCloseKey(key_handle)
    except:
        value_data = 'Not found'
    return value_data
