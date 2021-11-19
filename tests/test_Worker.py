#!/usr/bin/env python
# import
from __future__ import print_function
## batteries
import os
import sys
import pytest
import subprocess
## package
from sgepy import SGE

test_dir = os.path.dirname(__file__)
test_exe = os.path.join(os.path.dirname(test_dir), 'sgepy', 'tests.py')

# tests
def test_lambda():
    """
    simple lambda function
    """
    subprocess.run([test_exe])

def test_kwargs():
    """
    test using kwargs
    """
    subprocess.run([test_exe, '--test', 'kwargs'])

def test_mem():
    """
    test using kwargs
    """
    subprocess.run([test_exe, '--test', 'mem'])

def test_time():
    """
    test using kwargs
    """
    subprocess.run([test_exe, '--test', 'time'])
    
def test_pool():
    """
    test of pooling function
    """
    subprocess.run([test_exe, '--test', 'pool'])
