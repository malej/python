"""Tests for distutils.command.register."""
import sys
import os
import unittest
import getpass
import urllib
import warnings

from test.support import check_warnings

from distutils.command import register as register_module
from distutils.command.register import register
from distutils.core import Distribution
from distutils.errors import DistutilsSetupError

from distutils.tests import support
from distutils.tests.test_config import PYPIRC, PyPIRCCommandTestCase

PYPIRC_NOPASSWORD = """\
[distutils]

index-servers =
    server1

[server1]
username:me
"""

WANTED_PYPIRC = """\
[distutils]
index-servers =
    pypi

[pypi]
username:tarek
password:password
"""

class Inputs(object):
    """Fakes user inputs."""
    def __init__(self, *answers):
        self.answers = answers
        self.index = 0

    def __call__(self, prompt=''):
        try:
            return self.answers[self.index]
        finally:
            self.index += 1

class FakeOpener(object):
    """Fakes a PyPI server"""
    def __init__(self):
        self.reqs = []

    def __call__(self, *args):
        return self

    def open(self, req):
        self.reqs.append(req)
        return self

    def read(self):
        return 'xxx'

class RegisterTestCase(PyPIRCCommandTestCase):

    def setUp(self):
        PyPIRCCommandTestCase.setUp(self)
        # patching the password prompt
        self._old_getpass = getpass.getpass
        def _getpass(prompt):
            return 'password'
        getpass.getpass = _getpass
        self.old_opener = urllib.request.build_opener
        self.conn = urllib.request.build_opener = FakeOpener()

    def tearDown(self):
        getpass.getpass = self._old_getpass
        urllib.request.build_opener = self.old_opener
        PyPIRCCommandTestCase.tearDown(self)

    def _get_cmd(self, metadata=None):
        if metadata is None:
            metadata = {'url': 'xxx', 'author': 'xxx',
                        'author_email': 'xxx',
                        'name': 'xxx', 'version': 'xxx'}
        pkg_info, dist = self.create_dist(**metadata)
        return register(dist)

    def test_create_pypirc(self):
        # this test makes sure a .pypirc file
        # is created when requested.

        # let's create a register instance
        cmd = self._get_cmd()

        # we shouldn't have a .pypirc file yet
        self.assert_(not os.path.exists(self.rc))

        # patching input and getpass.getpass
        # so register gets happy
        #
        # Here's what we are faking :
        # use your existing login (choice 1.)
        # Username : 'tarek'
        # Password : 'password'
        # Save your login (y/N)? : 'y'
        inputs = Inputs('1', 'tarek', 'y')
        register_module.input = inputs.__call__
        # let's run the command
        try:
            cmd.run()
        finally:
            del register_module.input

        # we should have a brand new .pypirc file
        self.assert_(os.path.exists(self.rc))

        # with the content similar to WANTED_PYPIRC
        content = open(self.rc).read()
        self.assertEquals(content, WANTED_PYPIRC)

        # now let's make sure the .pypirc file generated
        # really works : we shouldn't be asked anything
        # if we run the command again
        def _no_way(prompt=''):
            raise AssertionError(prompt)
        register_module.input = _no_way

        cmd.show_response = 1
        cmd.run()

        # let's see what the server received : we should
        # have 2 similar requests
        self.assert_(self.conn.reqs, 2)
        req1 = dict(self.conn.reqs[0].headers)
        req2 = dict(self.conn.reqs[1].headers)

        self.assertEquals(req1['Content-length'], '1374')
        self.assertEquals(req2['Content-length'], '1374')
        self.assert_((b'xxx') in self.conn.reqs[1].data)

    def test_password_not_in_file(self):

        self.write_file(self.rc, PYPIRC_NOPASSWORD)
        cmd = self._get_cmd()
        cmd._set_config()
        cmd.finalize_options()
        cmd.send_metadata()

        # dist.password should be set
        # therefore used afterwards by other commands
        self.assertEquals(cmd.distribution.password, 'password')

    def test_registering(self):
        # this test runs choice 2
        cmd = self._get_cmd()
        inputs = Inputs('2', 'tarek', 'tarek@ziade.org')
        register_module.input = inputs.__call__
        try:
            # let's run the command
            cmd.run()
        finally:
            del register_module.input

        # we should have send a request
        self.assert_(self.conn.reqs, 1)
        req = self.conn.reqs[0]
        headers = dict(req.headers)
        self.assertEquals(headers['Content-length'], '608')
        self.assert_((b'tarek') in req.data)

    def test_password_reset(self):
        # this test runs choice 3
        cmd = self._get_cmd()
        inputs = Inputs('3', 'tarek@ziade.org')
        register_module.input = inputs.__call__
        try:
            # let's run the command
            cmd.run()
        finally:
            del register_module.input

        # we should have send a request
        self.assert_(self.conn.reqs, 1)
        req = self.conn.reqs[0]
        headers = dict(req.headers)
        self.assertEquals(headers['Content-length'], '290')
        self.assert_((b'tarek') in req.data)

    def test_strict(self):
        # testing the script option
        # when on, the register command stops if
        # the metadata is incomplete or if
        # long_description is not reSt compliant

        # empty metadata
        cmd = self._get_cmd({})
        cmd.ensure_finalized()
        cmd.strict = 1
        self.assertRaises(DistutilsSetupError, cmd.run)

        # we don't test the reSt feature if docutils
        # is not installed
        try:
            import docutils
        except ImportError:
            return

        # metadata are OK but long_description is broken
        metadata = {'url': 'xxx', 'author': 'xxx',
                    'author_email': 'xxx',
                    'name': 'xxx', 'version': 'xxx',
                    'long_description': 'title\n==\n\ntext'}

        cmd = self._get_cmd(metadata)
        cmd.ensure_finalized()
        cmd.strict = 1
        self.assertRaises(DistutilsSetupError, cmd.run)

        # now something that works
        metadata['long_description'] = 'title\n=====\n\ntext'
        cmd = self._get_cmd(metadata)
        cmd.ensure_finalized()
        cmd.strict = 1
        inputs = RawInputs('1', 'tarek', 'y')
        register_module.raw_input = inputs.__call__
        # let's run the command
        try:
            cmd.run()
        finally:
            del register_module.raw_input

        # strict is not by default
        cmd = self._get_cmd()
        cmd.ensure_finalized()
        inputs = RawInputs('1', 'tarek', 'y')
        register_module.raw_input = inputs.__call__
        # let's run the command
        try:
            cmd.run()
        finally:
            del register_module.raw_input

    def test_check_metadata_deprecated(self):
        # makes sure make_metadata is deprecated
        cmd = self._get_cmd()
        with check_warnings() as w:
            warnings.simplefilter("always")
            cmd.check_metadata()
            self.assertEquals(len(w.warnings), 1)

def test_suite():
    return unittest.makeSuite(RegisterTestCase)

if __name__ == "__main__":
    unittest.main(defaultTest="test_suite")
