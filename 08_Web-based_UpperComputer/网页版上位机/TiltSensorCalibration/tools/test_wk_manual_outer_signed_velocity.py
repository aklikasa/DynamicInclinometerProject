# -*- coding: utf-8 -*-
"""Legacy regression entrypoint: run the shared inner/outer WK manual velocity tests."""
import unittest
from test_wk_manual_signed_velocity_combined import TestSharedWKVelocity
if __name__=='__main__':
    unittest.main(verbosity=2)
