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
    ret = {}
    pythoncom.CoInitialize()
    try:
        ret.update(get_software())
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
    win32_products = get_software()
    for key, value in win32_products.iteritems():
        if target.lower() in key.lower():
            prd_name = value['name']
            prd_details = value
            search_results[prd_name] = prd_details
    return search_results

def get_software():
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
        if product.Name not in win32_products:
            win32_products[product.Name] = curr_product
    return win32_products