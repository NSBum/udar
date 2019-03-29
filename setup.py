import setuptools
from subprocess import Popen

with open('README.md', 'r') as fh:
    long_description = fh.read()

setuptools.setup(
    name='udar',
    version='0.0.1',
    author='Robert Reynolds',
    author_email='ReynoldsRJR@gmail.com',
    description='Detailed part-of-speech tagger for (accented) Russian.',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/reynoldsnlp/udar',
    packages=setuptools.find_packages(),
    install_requires=['hfst'],
    extras_require={'nltk': 'nltk'},
    # dependency_links=['https://github.com/ljos/pyvislcg3'],
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Operating System :: OS Independent',
    ],
)

try:
    Popen(['hfst-info'])
except FileNotFoundError:
    print('Command-line hfst not found. In order to use the built-in '
          'tokenizer, it must be installed, and in your PATH.')
    print('See http://divvun.no/doc/infra/compiling_HFST3.html\n')

try:
    import nltk
    assert nltk.download('punkt')
except ImportError:
    print('nltk is not installed, so its tokenizer is not available.')
    print('Try `python3 -m pip install --user nltk`.\n')
except AssertionError as e:
    print('nltk is installed, but tokenizer failed to download.', e)
    print("Try...\n>>> import nltk\n>>>nltk.download('punkt')\n")

try:
    Popen(['vislcg3'])
except FileNotFoundError:
    print('vislcg3 not found. In order to perform morphosyntactic '
          'disambiguation, it must be installed, and in your PATH.\n')
