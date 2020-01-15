"""Text object"""

from collections import Counter
import os
from pathlib import Path
from pkg_resources import resource_filename
import re
from subprocess import PIPE
from subprocess import Popen
import sys
from time import strftime
from typing import Callable
from typing import List
from typing import Tuple
from typing import Type
from typing import TypeVar
from typing import Union
from warnings import warn

from .fsts import get_fst
from .fsts import HFSTTokenizer
from .misc import destress
from .misc import result_names
from .misc import StressParams
from .misc import unspace_punct
from .tok import Token


__all__ = ['Text', 'hfst_tokenize']

RSRC_PATH = resource_filename('udar', 'resources/')
NEWLINE = '\n'

Tokenizer = Callable[[str], List[str]]
T = TypeVar('T', bound='Text')  # to annotate Text classmethods


def is_exe(fpath):
    return os.path.isfile(fpath) and os.access(fpath, os.X_OK)


def which(program):
    """UNIX `which`, from https://stackoverflow.com/a/377028/2903532"""
    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file
    return None


def hfst_tokenize(input_str: str) -> List[str]:
    try:
        p = Popen(['hfst-tokenize',
                   RSRC_PATH + 'tokeniser-disamb-gt-desc.pmhfst'],
                  stdin=PIPE,
                  stdout=PIPE,
                  universal_newlines=True)
        output, error = p.communicate(input_str)
        if error:
            print('ERROR (tokenizer):', error, file=sys.stderr)
        return output.rstrip().split('\n')
    except FileNotFoundError as e:
        raise FileNotFoundError('Command-line hfst must be installed to use '
                                'the tokenizer.') from e


def get_tokenizer(use_pexpect=True) -> Tokenizer:
    if which('hfst-tokenize'):
        if use_pexpect:
            return HFSTTokenizer()
        else:
            return hfst_tokenize
    else:
        try:
            import nltk  # type: ignore
            assert nltk.download('punkt')
        except ModuleNotFoundError as e:
            raise ModuleNotFoundError('Neither hfst or nltk are installed. '
                                      'One of them must be installed for '
                                      'tokenization.') from e
        except AssertionError as e:
            raise AssertionError("Cannot download nltk's `punkt` model. "
                                 'Connect to the internet & try again.') from e
        else:
            warn('hfst-tokenize not found. Using nltk.word_tokenize....',
                 ImportWarning)
            return nltk.word_tokenize


class Text:  # TODO inherit from `list`, put Toks in self ??
    """Sequence of `Token`s.

    An abbreviated `repr` can be achieved using string formatting:

    >>> t = Text('Мы хотим сократить repr этого объекта.')
    >>> repr(t)
    "Text('Мы хотим сократить repr этого объекта.')"
    >>> f'{t:8}'
    "Text('Мы хотим', 7 tokens)"
    """
    __slots__ = ['_tokenized', '_analyzed', '_disambiguated', '_from_str',
                 'orig', 'toks', 'Toks', 'text_name', 'experiment',
                 'annotation', 'features', '_feat_cache']
    _tokenized: bool
    _analyzed: bool
    _disambiguated: bool
    _from_str: bool
    orig: str
    toks: List[str]
    Toks: List[Token]
    text_name: str
    experiment: bool
    annotation: str
    features: Tuple
    _feat_cache: dict

    def __init__(self, input_text, tokenize=True, analyze=True,
                 disambiguate=False, tokenizer=None, analyzer=None,
                 gram_path=None, text_name=None, experiment=False,
                 annotation='', features=None, feat_cache=None,
                 from_file=False):
        """Note the difference between self.toks and self.Toks, where the
        latter is a list of Token objects, the former a list of strings.
        """
        self._analyzed = False
        self._disambiguated = False
        self._from_str = False
        self.Toks = []
        self.text_name = text_name
        self.experiment = experiment
        self.annotation = annotation
        if features is None:
            self.features = ()
        else:
            self.features = features
        if feat_cache is None:
            self._feat_cache = {}
        else:
            self._feat_cache = feat_cache
        if tokenizer is None:
            tokenizer = get_tokenizer()
        if isinstance(input_text, str):
            self._from_str = True
            if from_file:
                with open(input_text) as f:
                    self.orig = f.read()
            else:
                self.orig = input_text
            self._tokenized = False
            self.toks = []
        # elif input_text is a sequence of `str`s...
        elif ((hasattr(input_text, '__iter__')
               or hasattr(input_text, '__getitem__'))
              and isinstance(input_text[0], str)):
            if from_file:
                raise TypeError('With from_file set to True, input_text must '
                                'be a filename; sequence of str\'s given.')
            self.toks = input_text
            self._tokenized = True
            self.orig = ' '.join(input_text)
        # elif input_text is a sequence of `Token`s...
        elif ((hasattr(input_text, '__iter__')
               or hasattr(input_text, '__getitem__'))
              and isinstance(input_text[0], Token)):
            if from_file:
                raise TypeError('With from_file set to True, input_text must '
                                'be a filename; sequence of Tokens given.')
            self._analyzed = True
            self.Toks = input_text
            self.toks = [t.orig for t in input_text]
            self._tokenized = True
            self.orig = ' '.join(self.toks)
            return
        else:
            raise NotImplementedError('Expected `str`, '
                                      'or sequence of `str`s, '
                                      'or sequence of `Token`s; '
                                      f'got {type(input_text)}: '
                                      f'{repr(input_text)[:50]}...')
        if tokenize and not self.toks:
            self.tokenize(tokenizer=tokenizer)
        if analyze:
            self.analyze(analyzer=analyzer)
        if disambiguate:
            self.disambiguate(gram_path=gram_path)

    @classmethod
    def from_cg3(cls: Type[T], input_str: str, disambiguate=False,
                 **kwargs) -> T:
        """Initialize Text object from CG3 stream."""
        Toks = cls.parse_cg3(input_str)
        return cls(Toks, disambiguate=disambiguate, **kwargs)

    @classmethod
    def from_hfst(cls: Type[T], input_str: str, disambiguate=False,
                  **kwargs) -> T:
        """Initialize Text object from HFST stream."""
        Toks = cls.parse_hfst(input_str)
        return cls(Toks, disambiguate=disambiguate, **kwargs)

    def __format__(self, format_spec: str):
        tok_count = len(self.toks)
        tok_count_str = f', {tok_count} tokens'
        if not format_spec:
            return f'Text({self.orig!r}{tok_count_str})'
        return f'Text({self.orig[:int(format_spec)]!r}{tok_count_str})'

    def __repr__(self):
        return f'Text({self.orig!r})'

    def __str__(self):
        return self.hfst_str()

    def hfst_str(self) -> str:
        """Text HFST-/XFST-style stream."""
        try:
            return '\n\n'.join(t.hfst_str() for t in self.Toks) + '\n\n'
        except TypeError:
            try:
                return f'(Text (not analyzed) {self.toks[:10]})'
            except TypeError:
                return f'(Text (not tokenized) {self.orig[:30]})'

    def cg3_str(self, traces=False, annotated=False) -> str:
        """Text CG3-style stream."""
        if annotated and self.annotation:
            ann = f'TEXT: {self.annotation}\n'
        else:
            ann = ''
        return f"{ann}{NEWLINE.join(t.cg3_str(traces=traces, annotated=annotated) for t in self.Toks)}\n\n"  # noqa: E501

    def __lt__(self, other):
        return self.Toks < other.Toks

    def __eq__(self, other):
        return self.Toks == other.Toks

    def __hash__(self):
        return hash(self.Toks)

    def __len__(self):
        return len(self.Toks)

    def __getitem__(self, i: int) -> Union[Token, str]:
        # TODO return only Token or str, not either
        try:
            return self.Toks[i]
        except TypeError:
            try:
                return self.toks[i]
            except TypeError as e:
                raise TypeError('Text not yet tokenized. Try Text.tokenize() '
                                'or Text.analyze() first.') from e

    def __iter__(self):
        try:
            return (t for t in self.Toks)
        except TypeError as e:
            raise TypeError('Text object only iterable after morphological '
                            'analysis. Try Text.analyze() first.') from e

    def tokenize(self, tokenizer=None) -> None:
        """Tokenize Text using `tokenizer`."""
        if tokenizer is None:
            tokenizer = get_tokenizer()
        self.toks = tokenizer(self.orig)
        self._tokenized = True

    def analyze(self, analyzer=None, experiment=None) -> None:
        """Analyze Text's self.toks."""
        if analyzer is None:
            analyzer = get_fst('analyzer')
        if experiment is None:
            experiment = self.experiment
        if experiment:
            self.Toks = [analyzer.lookup(destress(t)) for t in self.toks]
        else:
            self.Toks = [analyzer.lookup(t) for t in self.toks]
        self._analyzed = True

    def disambiguate(self, gram_path=None, traces=True) -> None:
        """Remove Text's readings using CG3 grammar at gram_path."""
        if gram_path is None:
            gram_path = RSRC_PATH + 'disambiguator.cg3'
        elif isinstance(gram_path, str):
            pass
        elif isinstance(gram_path, Path):
            gram_path = repr(gram_path)
        else:
            raise NotImplementedError('Unexpected grammar path. Use str.')
        if traces:
            cmd = ['vislcg3', '-t', '-g', gram_path]
        else:
            cmd = ['vislcg3', '-g', gram_path]
        try:
            p = Popen(cmd, stdin=PIPE, stdout=PIPE, universal_newlines=True)
        except FileNotFoundError as e:
            raise FileNotFoundError('vislcg3 must be installed and be in your '
                                    'PATH variable to disambiguate a text.') from e  # noqa: E501
        output, error = p.communicate(input=self.cg3_str())
        new_Toks = self.parse_cg3(output)
        if len(self.Toks) != len(new_Toks):
            triangle = '\u25B6'
            raise AssertionError('parse_cg3: output len does not match! '
                                 f'{len(self.Toks)} --> {len(new_Toks)}\n' +
                                 '\n\n'.join(f'{old} {triangle} {new}'
                                             for old, new
                                             in zip(self.Toks, new_Toks)))
        for old, new in zip(self.Toks, new_Toks):
            old.readings = new.readings
            old.removed_readings += new.removed_readings
            old.lemmas = new.lemmas
        self._disambiguated = True

    @staticmethod
    def parse_hfst(stream: str) -> List[Token]:
        """Convert hfst stream into list of `Token`s."""
        output = []
        for cohort in stream.strip().split('\n\n'):
            readings = []
            for line in cohort.split('\n'):
                try:
                    token, reading, weight = line.split('\t')
                except ValueError as e:
                    raise ValueError(line) from e
                readings.append((reading, weight, ''))
            output.append(Token(token, readings))
        return output

    @staticmethod
    def parse_cg3(stream: str) -> List[Token]:
        """Convert cg3 stream into list of `Token`s."""
        output = []
        readings = []
        rm_readings = []

        # declare types that mypy cannot determine automatically
        o_rm, o_read, o_weight, o_rule, o_tok = [''] * 5

        for line in stream.split('\n'):
            # parse and get state: 0-token, 1-reading, 2+-sub-reading
            n_tok_match = re.match('"<((?:.|\")*)>"', line)
            if n_tok_match:
                n_tok = n_tok_match.group(1)
                n_state = 0
                try:
                    float(o_weight)  # to trigger ValueError on first line
                    if not o_rm:
                        readings.append((o_read, o_weight, o_rule))
                    else:
                        rm_readings.append((o_read, o_weight, o_rule))
                    t = Token(o_tok, readings, removed_readings=rm_readings)
                    output.append(t)
                except ValueError:  # float('') occurs on the first line
                    pass
                readings = []
                rm_readings = []
                o_tok, o_state = n_tok, n_state
            else:
                line_match = re.match(r'(;)?(\t+)"((?:.|\")*)" (.*?) <W:(.*)> ?(.*)$', line)  # noqa: E501
                if line_match:
                    n_rm, n_tabs, n_lemma, n_tags, n_weight, n_rule = line_match.groups()  # noqa: E501
                else:
                    if line:
                        print('WARNING (parse_cg3) unrecognized line:', line,
                              file=sys.stderr)
                    continue
                if n_rule:
                    n_rule = f' {n_rule}'
                n_state = len(n_tabs)

                if n_state == 1:
                    if o_state >= 1:
                        # append previous reading
                        if not o_rm:
                            readings.append((o_read, o_weight, o_rule))
                        else:
                            rm_readings.append((o_read, o_weight, o_rule))  # noqa: E501
                    n_read = f"{n_lemma}+{n_tags.replace(' ', '+')}"
                    # rotate values from new to old
                    o_rm, o_weight, o_rule, o_read, o_state = n_rm, n_weight, n_rule, n_read, n_state  # noqa: E501
                else:  # if n_state > 1
                    # add subreading to reading
                    n_read = f"{n_lemma}+{n_tags.replace(' ', '+')}#{o_read}"
                    # rotate values from new to old
                    o_weight, o_rule, o_read, o_state = n_weight, n_rule, n_read, n_state  # noqa: E501
        if not o_rm:
            readings.append((o_read, o_weight, o_rule))
        else:
            rm_readings.append((o_read, o_weight, o_rule))
        t = Token(o_tok, readings, removed_readings=rm_readings)
        output.append(t)
        return output

    def stressify(self, selection='safe', guess=False, experiment=None,
                  lemmas={}) -> str:
        """Text: Return str of running text with stress marked.

        selection  (Applies only to words in the lexicon.)
            safe   -- Only add stress if it is unambiguous.
            freq   -- lemma+reading > lemma > reading
            rand   -- Randomly choose between specified stress positions.
            all    -- Add stress to all possible specified stress positions.

        guess
            Applies only to out-of-lexicon words. Makes an "intelligent" guess.

        experiment
            1) Remove stress from Token.orig
            2) Save prediction in each Token.stress_predictions[stress_params]

        lemmas -- dict of {token: lemma} pairs.
            Limit readings of given tokens to the lemma value.
            For example, lemmas={'моя': 'мой'} would limit readings for every
            instance of the token `моя` to those with the lemma `мой`, thereby
            ignoring readings with the lemma `мыть`. Currently, the token is
            case-sensitive!
        """
        if experiment is None:
            experiment = self.experiment
        out_text = [t.stressify(disambiguated=self._disambiguated,
                                selection=selection, guess=guess,
                                experiment=experiment,
                                lemma=lemmas.get(t.orig, None))
                    for t in self.Toks]
        return self.respace(out_text)

    def stress_eval(self, stress_params: StressParams) -> Counter:
        """Text: get dictionary of evaluation metrics of stress predictions."""
        V = 'аэоуыяеёюи'
        counts = Counter(t.stress_predictions[stress_params][1]
                         for t in self.Toks)
        counts['N_ambig'] = len([1 for t in self.Toks
                                 if (t.stress_ambig > 1
                                     and (len(re.findall(f'[{V}]', t.orig))
                                          > 1))])
        return counts

    def stress_preds2tsv(self, path=None, timestamp=True,
                         filename=None) -> None:
        """From Text, write a tab-separated file with aligned predictions
        from experiment.

        orig        <params>    <params>
        Мы          Мы́          Мы́
        говори́ли    го́ворили    гово́рили
        с           с           с
        ни́м         ни́м         ни́м
        .           .           .
        """
        if path is None:
            path = Path('')
        else:
            path = Path(path)
            path.mkdir(parents=True, exist_ok=True)
        if timestamp:
            prefix = strftime("%Y%m%d-%H%M%S")
        else:
            prefix = ''
        if filename is None:
            path = path / Path(f'{prefix}_{self.text_name}.tsv')
        else:
            path = path / Path(f'{prefix}{filename}')
        SPs = sorted(self.Toks[0].stress_predictions.keys())
        readable_SPs = [sp.readable_name() for sp in SPs]
        with path.open('w') as f:
            print('orig', *readable_SPs, 'perfect', 'all_bad', 'ambig',
                  'CG_fixed_it', 'reads', sep='\t', file=f)
            for t in self.Toks:
                # '  '.join([result_names[t.stress_predictions[sp][1]],
                preds = [f'{t.stress_predictions[sp][0]} {result_names[t.stress_predictions[sp][1]]}'  # noqa: E501
                         for sp in SPs]
                perfect = all(p == t.orig for p in preds)
                all_bad = all(p != t.orig for p in preds)
                print(t.orig, *preds, perfect, all_bad, t.stress_ambig,
                      t.stress_ambig and len(t.stresses()) < 2,
                      f'{t.readings} ||| {t.removed_readings}',
                      sep='\t', file=f)

    def phoneticize(self, selection='safe', guess=False, experiment=False,
                    context=False) -> str:
        """Text: Return str of running text of phonetic transcription.

        selection  (Applies only to words in the lexicon.)
            safe   -- Only add stress if it is unambiguous.
            freq   -- lemma+reading > lemma > reading
            rand   -- Randomly choose between specified stress positions.
            all    -- Add stress to all possible specified stress positions.

        guess
            Applies only to out-of-lexicon words. Makes an "intelligent" guess.

        experiment
            1) Remove stress from Token.orig
            2) Save prediction in each Token.stress_predictions[stress_params]

        context
            Applies phonetic transcription based on context between words
        """
        if context:
            raise NotImplementedError('The context keyword argument is not '
                                      'implemented yet.')
        out_text = []
        for t in self.Toks:
            out_text.append(t.phoneticize(disambiguated=self._disambiguated,
                                          selection=selection, guess=guess,
                                          experiment=experiment))
        return self.respace(out_text)

    def respace(self, toks: List[str]) -> str:
        """Attempt to restore/normalize spacing (esp. around punctuation)."""
        # TODO re-evaluate this
        if self._from_str:
            try:
                return unspace_punct(' '.join(toks))
            except TypeError:
                print(toks, file=sys.stderr)
                return unspace_punct(' '.join(t if t else 'UDAR.None'
                                              for t in toks))
        elif isinstance(toks, list):
            # for match in re.finditer(r'\s+', self.orig):
            raise NotImplementedError(f'Cannot respace {self}.')
        else:
            return unspace_punct(' '.join(toks))
