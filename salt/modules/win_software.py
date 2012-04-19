'''
Module for finding installed software on Windows systems
'''
try:
    import pythoncom
    import threading
    import ctypes
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
    return 'software'

def list():
    '''
    returns a dict with all software found on the windows machine
    CLI Example::
        salt '*' software.list()
    '''
    pythoncom.CoInitialize()
    try:
        ret = dict(get_reg_software().items() + get_msi_software().items())
    finally:
        pythoncom.CoUninitialize()
    return ret

def find(pattern):
    '''
    returns a dict with specific items of interest
    CLI Example::
        salt '*' software.find('foo')
    '''
    ret = {}
    pythoncom.CoInitialize()
    try:
        ret = search_software(pattern)
    finally:
        pythoncom.CoUninitialize()
    return ret

def search_software(target):
    '''
    This searches the msi product databases for name matches
    of the list of target products, it will return a dict with
    values added to the list passed in
    '''
    search_results = {}
    software = dict(get_reg_software().items() + get_msi_software().items())
    for key, value in software.iteritems():
        if key is not None:
            if target.lower() in key.lower():
                prd_name = value['name']
                prd_details = value
                search_results[prd_name] = prd_details
    return search_results

def get_msi_software():
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
        curr_product = {}
        curr_product['name'] = product.Name
        curr_product['version'] = product.Version
        curr_product['description'] = product.Description
        curr_product['id_number'] = product.IdentifyingNumber
        curr_product['install_date'] = product.InstallDate
        curr_product['install_location'] = product.InstallLocation
        curr_product['install_state'] = product.InstallState
        curr_product['package_cache'] = product.PackageCache
        curr_product['sku_number'] = product.SKUNumber
        curr_product['vendor'] = product.Vendor
        curr_product['found in'] = 'msi database'
        if product.Name not in win32_products:
            win32_products[product.Name] = curr_product
    return win32_products

def get_reg_software():
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
    reg_entries = dict(get_user_keys().items() + get_machine_keys().items())
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
                prd_name = get_reg_value(
                    reg_hive,
                    prd_uninst_key,
                    "DisplayName")
                prd_ver = get_reg_value(
                    reg_hive,
                    prd_uninst_key,
                    "DisplayVersion")
                prd_install_date = get_reg_value(
                    reg_hive,
                    prd_uninst_key,
                    "InstallDate")
                prd_install_location = get_reg_value(
                    reg_hive,
                    prd_uninst_key,
                    "InstallLocation")
                curr_product = {}
                curr_product['name'] = prd_name
                curr_product['version'] = prd_ver
                curr_product['install_date'] = prd_install_date
                curr_product['install_location'] = prd_install_location
                curr_product['found_in'] = prd_uninst_key
                if not name in ignore_list:
                    reg_software[name] = curr_product
    return reg_software

def get_machine_keys():
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

def get_user_keys():
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

def get_reg_value(reg_hive, reg_key, value_name=''):
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
