from setuptools import setup

setup(
    name = "stacklesslib",
    packages = ["stacklesslib", "stacklesslib.replacements"],
    version = "1.0.4",
    description = "Standard Stackless Python supporting functionality",
    author = "Richard Tew",
    author_email = "richard.m.tew@gmail.com",
    url = "http://pypi.python.org/pypi/stacklesslib",
    keywords = ["microthreads", "coroutines", "stackless", "monkeypatching"],
    classifiers = [
        "Programming Language :: Python",
        "Programming Language :: Python :: 2",
        "Development Status :: 5 - Production/Stable",
        "Environment :: Other Environment",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: Software Development :: Libraries :: Python Modules",
        ],
    long_description = open("README.txt").read()
)
