'''
Classes that manage file clients
'''
# Import python libs
import BaseHTTPServer
import contextlib
import logging
import hashlib
import os
import shutil
import stat
import string
import subprocess
import urllib2
import urlparse

# Import third-party libs
import yaml
import zmq

# Import salt libs
from salt.exceptions import MinionError
import salt.client
import salt.crypt
import salt.loader
import salt.utils
import salt.payload

log = logging.getLogger(__name__)

def get_file_client(opts):
    '''
    Read in the ``file_client`` option and return the correct type of file
    server
    '''
    try:
        return {
                'remote': RemoteClient,
                'local': LocalClient
               }.get(opts['file_client'], 'remote')(opts)
    except KeyError:
        return RemoteClient(opts)

class Client(object):
    '''
    Base class for Salt file interactions
    '''
    def __init__(self, opts):
        self.opts = opts
        self.serial = salt.payload.Serial(self.opts)
    
    def _check_proto(self, path):
        '''
        Make sure that this path is intended for the salt master and trim it
        '''
        if not path.startswith('salt://'):
            raise MinionError('Unsupported path: {0}'.format(path))
        return path[7:]

    def _file_local_list(self, dest):
        '''
        Helper util to return a list of files in a directory
        '''
        if os.path.isdir(dest):
            destdir = dest
        else:
            destdir = os.path.dirname(dest)

        filelist = []

        for root, dirs, files in os.walk(destdir):
            for name in files:
                path = os.path.join(root, name)
                filelist.append(path)

        return filelist

    def _cache_loc(self, path, env='base'):
        '''
        Return the local location to cache the file, cache dirs will be made
        '''
        dest = os.path.join(
            self.opts['cachedir'],
            'files',
            env,
            path
            )
        destdir = os.path.dirname(dest)
        cumask = os.umask(191)
        if not os.path.isdir(destdir):
            os.makedirs(destdir)
        os.chmod(dest, 384)
        os.umask(cumask)
        return dest

    def cache_file(self, path, env='base'):
        '''
        Pull a file down from the file server and store it in the minion
        file cache
        '''
        return self.get_url(path, '', True, env)

    def cache_files(self, paths, env='base'):
        '''
        Download a list of files stored on the master and put them in the
        minion file cache
        '''
        ret = []
        for path in paths:
            ret.append(self.cache_file(path, env))
        return ret

    def cache_master(self, env='base'):
        '''
        Download and cache all files on a master in a specified environment
        '''
        ret = []
        for path in self.file_list(env):
            ret.append(self.cache_file('salt://{0}'.format(path), env))
        return ret

    def cache_dir(self, path, env='base'):
        '''
        Download all of the files in a subdir of the master
        '''
        ret = []
        path = self._check_proto(path)
        for fn_ in self.file_list(env):
            if fn_.startswith(path):
                local = self.cache_file('salt://{0}'.format(fn_), env)
                if not fn_.strip():
                    continue
                ret.append(local)
        return ret

    def cache_local_file(self, path, **kwargs):
        '''
        Cache a local file on the minion in the localfiles cache
        '''
        dest = os.path.join(self.opts['cachedir'], 'localfiles',
                path.lstrip('/'))
        destdir = os.path.dirname(dest)

        if not os.path.isdir(destdir):
            os.makedirs(destdir)

        shutil.copyfile(path, dest)
        return dest

    def file_local_list(self, env='base'):
        '''
        List files in the local minion files and localfiles caches
        '''
        filesdest = os.path.join(self.opts['cachedir'], 'files', env)
        localfilesdest = os.path.join(self.opts['cachedir'], 'localfiles')

        return sorted(self._file_local_list(filesdest) +
                self._file_local_list(localfilesdest))

    def file_list(self, env='base'):
        '''
        This function must be overwritten
        '''
        return []

    def is_cached(self, path, env='base'):
        '''
        Returns the full path to a file if it is cached locally on the minion
        otherwise returns a blank string
        '''
        localsfilesdest = os.path.join(
                self.opts['cachedir'], 'localfiles', path.lstrip('/'))
        filesdest = os.path.join(
                self.opts['cachedir'], 'files', env, path.lstrip('salt://'))

        if os.path.exists(filesdest):
            return filesdest
        elif os.path.exists(localsfilesdest):
            return localsfilesdest

        return ''

    def get_state(self, sls, env):
        '''
        Get a state file from the master and store it in the local minion
        cache return the location of the file
        '''
        if '.' in sls:
            sls = sls.replace('.', '/')
        for path in ['salt://' + sls + '.sls',
                     os.path.join('salt://', sls, 'init.sls')]:
            dest = self.cache_file(path, env)
            if dest:
                return dest
        return False

    def get_dir(self, path, dest='', env='base'):
        '''
        Get a directory recursively from the salt-master
        '''
        # TODO: We need to get rid of using the string lib in here
        ret = []
        # Strip trailing slash
        path = string.rstrip(self._check_proto(path), '/')
        # Break up the path into a list containing the bottom-level directory
        # (the one being recursively copied) and the directories preceding it
        separated = string.rsplit(path,'/',1)
        if len(separated) != 2:
            # No slashes in path. (This means all files in env will be copied)
            prefix = ''
        else:
            prefix = separated[0]

        # Copy files from master
        for fn_ in self.file_list(env):
            if fn_.startswith(path):
                # Remove the leading directories from path to derive
                # the relative path on the minion.
                minion_relpath = string.lstrip(fn_[len(prefix):],'/')
                ret.append(self.get_file('salt://{0}'.format(fn_),
                                         '%s/%s' % (dest,minion_relpath),
                                         True, env))
        # Replicate empty dirs from master
        for fn_ in self.file_list_emptydirs(env):
            if fn_.startswith(path):
                # Remove the leading directories from path to derive
                # the relative path on the minion.
                minion_relpath = string.lstrip(fn_[len(prefix):],'/')
                minion_mkdir = '%s/%s' % (dest,minion_relpath)
                os.makedirs(minion_mkdir)
                ret.append(minion_mkdir)
        ret.sort()
        return ret

    def get_url(self, url, dest, makedirs=False, env='base'):
        '''
        Get a single file from a URL.
        '''
        url_data = urlparse.urlparse(url)
        if url_data.scheme == 'salt':
            return self.get_file(url, dest, makedirs, env)
        if dest:
            destdir = os.path.dirname(dest)
            if not os.path.isdir(destdir):
                if makedirs:
                    os.makedirs(destdir)
                else:
                    return ''
        else:
            dest = os.path.join(
                self.opts['cachedir'],
                'extrn_files',
                env,
                os.path.join(
                    url_data.netloc,
                    os.path.relpath(url_data.path, '/'))
                )
            destdir = os.path.dirname(dest)
            if not os.path.isdir(destdir):
                os.makedirs(destdir)
        try:
            with contextlib.closing(urllib2.urlopen(url)) as srcfp:
                with open(dest, 'wb') as destfp:
                    shutil.copyfileobj(srcfp, destfp)
            return dest
        except urllib2.HTTPError, ex:
            raise MinionError('HTTP error {0} reading {1}: {3}'.format(
                    ex.code,
                    url,
                    *BaseHTTPServer.BaseHTTPRequestHandler.responses[ex.code]))
        except urllib2.URLError, ex:
            raise MinionError('Error reading {0}: {1}'.format(url, ex.reason))
        return ''

class LocalClient(Client):
    '''
    Use the local_roots option to parse a local file root
    '''
    def __init__(self, opts):
        Client.__init__(self, opts)

    def _find_file(self, path, env='base'):
        '''
        Locate the file path
        '''
        fnd = {'path': '',
               'rel': ''}
        if env not in self.opts['file_roots']:
            return fnd
        for root in self.opts['file_roots'][env]:
            full = os.path.join(root, path)
            if os.path.isfile(full):
                fnd['path'] = full
                fnd['rel'] = path
                return fnd
        return fnd

    def get_file(self, path, dest='', makedirs=False, env='base'):
        '''
        Coppies a file from the local files directory and coppies it into place
        '''
        path = self._check_proto(path)
        fnd = self._find_file(path, env)
        if not dest:
            dest = _cache_loc(path, env)
        destdir = os.path.dirname(dest)
        if not os.path.isdir(destdir):
            if makedirs:
                os.makedirs(destdir)
            else:
                return False
        shutil.copy(fnd['path'], dest)
        return dest

    def file_list(self, env='base'):
        '''
        Return a list of files in the given environment
        '''
        ret = []
        if env not in self.opts['file_roots']:
            return ret
        for path in self.opts['file_roots'][env]:
            for root, dirs, files in os.walk(path):
                for fn in files:
                    ret.append(
                        os.path.relpath(
                            os.path.join(
                                root,
                                fn
                                ),
                            path
                            )
                        )
        return ret

    def file_list_emptydirs(self, env='base'):
        '''
        List the empty dirs in the file_roots
        '''
        ret = []
        if env not in self.opts['file_roots']:
            return ret
        for path in self.opts['file_roots'][env]:
            for root, dirs, files in os.walk(path):
                if len(dirs)==0 and len(files)==0:
                    ret.append(os.path.relpath(root,path))
        return ret

    def hash_file(self, path, env='base'):
        '''
        Return the hash of a file, to get the hash of a file in the file_roots
        prepend the path with salt://<file on server> otherwise, prepend the
        file with / for a local file.
        '''
        ret = {}
        try:
            path = self._check_proto(path)
        except MinionError:
            if not os.path.isfile(path):
                err = ('Specified file {0} is not present to generate '
                        'hash').format(path)
                log.warning(err)
                return ret
            else:
                ret['hsum'] = hashlib.md5(open(path, 'rb').read()).hexdigest()
                ret['hash_type'] = 'md5'
                return ret
        path = self._find_file(path, env)['path']
        if not path:
            return {}
        ret = {}
        ret['hsum'] = getattr(hashlib, self.opts['hash_type'])(
                open(path, 'rb').read()).hexdigest()
        ret['hash_type'] = self.opts['hash_type']
        return ret
 
    def list_env(self, path, env='base'):
        '''
        Return a list of the files in the file server's specified environment
        '''
        return self.file_list(env)

    def master_opts(self):
        '''
        Return the master opts data
        '''
        return self.opts

    def ext_nodes(self):
        '''
        Return the metadata derived from the external nodes system on the local
        system
        '''
        if not self.opts['external_nodes']:
            return {}
        if not salt.utils.which(self.opts['external_nodes']):
            log.error(('Specified external nodes controller {0} is not'
                       ' available, please verify that it is installed'
                       '').format(self.opts['external_nodes']))
            return {}
        cmd = '{0} {1}'.format(self.opts['external_nodes'], self.opts['id'])
        ndata = yaml.safe_load(
                subprocess.Popen(
                    cmd,
                    shell=True,
                    stdout=subprocess.PIPE
                    ).communicate()[0])
        ret = {}
        if 'environment' in ndata:
            env = ndata['environment']
        else:
            env = 'base'

        if 'classes' in ndata:
            if isinstance(ndata['classes'], dict):
                ret[env] = ndata['classes'].keys()
            elif isinstance(ndata['classes'], list):
                ret[env] = ndata['classes']
            else:
                return ret
        return ret


class RemoteClient(Client):
    '''
    Interact with the salt master file server.
    '''
    def __init__(self, opts):
        Client.__init__(self, opts)
        self.auth = salt.crypt.SAuth(opts)
        self.socket = self.__get_socket()

    def __get_socket(self):
        '''
        Return the ZeroMQ socket to use
        '''
        context = zmq.Context()
        socket = context.socket(zmq.REQ)
        socket.connect(self.opts['master_uri'])
        return socket

    def get_file(self, path, dest='', makedirs=False, env='base'):
        '''
        Get a single file from the salt-master
        path must be a salt server location, aka, salt://path/to/file, if
        dest is ommited, then the downloaded file will be placed in the minion
        cache
        '''
        path = self._check_proto(path)
        payload = {'enc': 'aes'}
        fn_ = None
        if dest:
            destdir = os.path.dirname(dest)
            if not os.path.isdir(destdir):
                if makedirs:
                    os.makedirs(destdir)
                else:
                    return False
            fn_ = open(dest, 'w+')
        load = {'path': path,
                'env': env,
                'cmd': '_serve_file'}
        while True:
            if not fn_:
                load['loc'] = 0
            else:
                load['loc'] = fn_.tell()
            payload['load'] = self.auth.crypticle.dumps(load)
            self.socket.send(self.serial.dumps(payload))
            data = self.auth.crypticle.loads(self.serial.loads(self.socket.recv()))
            if not data['data']:
                if not fn_ and data['dest']:
                    # This is a 0 byte file on the master
                    dest = os.path.join(
                        self.opts['cachedir'],
                        'files',
                        env,
                        data['dest']
                        )
                    destdir = os.path.dirname(dest)
                    cumask = os.umask(stat.S_IRWXG | stat.S_IRWXO)
                    if not os.path.isdir(destdir):
                        os.makedirs(destdir)
                    if not os.path.exists(dest):
                        open(dest, 'w+').write(data['data'])
                    os.chmod(dest, stat.S_IRUSR | stat.S_IWUSR)
                    os.umask(cumask)
                break
            if not fn_:
                dest = os.path.join(
                    self.opts['cachedir'],
                    'files',
                    env,
                    data['dest']
                    )
                destdir = os.path.dirname(dest)
                cumask = os.umask(stat.S_IRWXG | stat.S_IRWXO)
                if not os.path.isdir(destdir):
                    os.makedirs(destdir)
                fn_ = open(dest, 'w+')
                os.chmod(dest, stat.S_IRUSR | stat.S_IWUSR)
                os.umask(cumask)
            fn_.write(data['data'])
        return dest

    def file_list(self, env='base'):
        '''
        List the files on the master
        '''
        payload = {'enc': 'aes'}
        load = {'env': env,
                'cmd': '_file_list'}
        payload['load'] = self.auth.crypticle.dumps(load)
        self.socket.send(self.serial.dumps(payload))
        return self.auth.crypticle.loads(self.serial.loads(self.socket.recv()))

    def file_list_emptydirs(self, env='base'):
        '''
        List the empty dirs on the master
        '''
        payload = {'enc': 'aes'}
        load = {'env': env,
                'cmd': '_file_list_emptydirs'}
        payload['load'] = self.auth.crypticle.dumps(load)
        self.socket.send(self.serial.dumps(payload))
        return self.auth.crypticle.loads(self.serial.loads(self.socket.recv()))

    def hash_file(self, path, env='base'):
        '''
        Return the hash of a file, to get the hash of a file on the salt
        master file server prepend the path with salt://<file on server>
        otherwise, prepend the file with / for a local file.
        '''
        try:
            path = self._check_proto(path)
        except MinionError:
            if not os.path.isfile(path):
                err = ('Specified file {0} is not present to generate '
                        'hash').format(path)
                log.warning(err)
                return {}
            else:
                ret = {}
                ret['hsum'] = hashlib.md5(open(path, 'rb').read()).hexdigest()
                ret['hash_type'] = 'md5'
                return ret
        payload = {'enc': 'aes'}
        load = {'path': path,
                'env': env,
                'cmd': '_file_hash'}
        payload['load'] = self.auth.crypticle.dumps(load)
        self.socket.send(self.serial.dumps(payload))
        return self.auth.crypticle.loads(self.serial.loads(self.socket.recv()))

    def list_env(self, path, env='base'):
        '''
        Return a list of the files in the file server's specified environment
        '''
        payload = {'enc': 'aes'}
        load = {'env': env,
                'cmd': '_file_list'}
        payload['load'] = self.auth.crypticle.dumps(load)
        self.socket.send(self.serial.dumps(payload))
        return self.auth.crypticle.loads(self.serial.loads(self.socket.recv()))

    def master_opts(self):
        '''
        Return the master opts data
        '''
        payload = {'enc': 'aes'}
        load = {'cmd': '_master_opts'}
        payload['load'] = self.auth.crypticle.dumps(load)
        self.socket.send(self.serial.dumps(payload))
        return self.auth.crypticle.loads(self.serial.loads(self.socket.recv()))

    def ext_nodes(self):
        '''
        Return the metadata derived from the external nodes system on the
        master.
        '''
        payload = {'enc': 'aes'}
        load = {'cmd': '_ext_nodes',
                'id': self.opts['id']}
        payload['load'] = self.auth.crypticle.dumps(load)
        self.socket.send(self.serial.dumps(payload))
        return self.auth.crypticle.loads(self.serial.loads(self.socket.recv()))