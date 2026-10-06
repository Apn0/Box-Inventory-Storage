#!/bin/bash
pip install autopep8
autopep8 --in-place --aggressive tests/test_build.py
