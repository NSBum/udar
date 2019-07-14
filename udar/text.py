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

from .fsts import get_fst
from .misc import destress
from .misc import result_names
from .misc import unspace_punct
from .tok import Token


__all__ = ['Text', 'hfst_tokenize']

RSRC_PATH = resource_filename('udar', 'resources/')


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


def hfst_tokenize(text):
    try:
        p = Popen(['hfst-tokenize',
                   RSRC_PATH + 'tokeniser-disamb-gt-desc.pmhfst'],
                  stdin=PIPE,
                  stdout=PIPE,
                  universal_newlines=True)
        output, error = p.communicate(text)
        if error:
            print('ERROR (tokenizer):', error, file=sys.stderr)
        return output.rstrip().split('\n')
    except FileNotFoundError:
        print('Command-line hfst must be installed to use the tokenizer.',
              file=sys.stderr)
        raise


def get_tokenizer():
    if which('hfst-tokenize'):
        return hfst_tokenize
    else:
        try:
            from nltk import word_tokenize as nltk_tokenize
            return nltk_tokenize
        except ModuleNotFoundError:
            print('hfst-tokenize and nltk.word_tokenize not found. '
                  'One of them must be installed for tokenization.',
                  file=sys.stderr)
            raise


class Text:
    """Sequence of `Token`s."""
    __slots__ = ['_tokenized', '_analyzed', '_disambiguated', '_from_str',
                 'orig', 'toks', 'Toks', 'text_name', 'experiment']

    def __init__(self, input_text, tokenize=True, analyze=True,
                 disambiguate=False, tokenizer=None,
                 analyzer=None, gram_path=None, text_name=None,
                 experiment=False):
        """Note the difference between self.toks and self.Toks, where the
        latter is a list of Token objects, the former a list of strings.
        """
        self._analyzed = False
        self._disambiguated = False
        self.Toks = None
        self.text_name = text_name
        self.experiment = experiment
        if tokenizer is None:
            tokenizer = get_tokenizer()
        if isinstance(input_text, str):
            self._from_str = True
            self.orig = input_text
            self._tokenized = False
            self.toks = None
        elif isinstance(input_text, list):
            self._from_str = False
            self.orig = ' '.join(input_text)
            self._tokenized = True
            self.toks = input_text
        else:
            t = type(input_text)
            print(f'Expected `str` or `list`, got {t}.', file=sys.stderr)
            raise NotImplementedError
        if tokenize and not self.toks:
            self.tokenize(tokenizer=tokenizer)
        if analyze:
            self.analyze(analyzer=analyzer)
        if disambiguate:
            self.disambiguate(gram_path=gram_path)

    def __repr__(self):
        """Text HFST-/XFST-style stream."""
        try:
            return '\n\n'.join(t.hfst_stream() for t in self.Toks) + '\n\n'
        except TypeError:
            try:
                return f'(Text (not analyzed) {self.toks[:10]})'
            except TypeError:
                return f'(Text (not tokenized) {self.orig[:30]})'

    def CG_str(self, traces=False):
        """Text CG3-style stream."""
        return '\n'.join(t.cg3_stream(traces=traces) for t in self.Toks) + '\n\n'  # noqa: E501

    def __getitem__(self, i):
        try:
            return self.Toks[i]
        except TypeError:
            try:
                return self.toks[i]
            except TypeError:
                print('Text object not yet tokenized. Try Text.tokenize() '
                      'or Text.analyze() first.', file=sys.stderr)
                raise

    def __iter__(self):
        try:
            return (t for t in self.Toks)
        except TypeError:
            print('Text object only iterable after morphological analysis. '
                  'Try Text.analyze() first.', file=sys.stderr)
            raise

    def tokenize(self, tokenizer=None):
        """Tokenize Text using `tokenizer`."""
        if tokenizer is None:
            tokenizer = self.tokenizer
        self.toks = tokenizer(self.orig)
        self._tokenized = True

    def analyze(self, analyzer=None, experiment=None):
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

    def disambiguate(self, gram_path=None, traces=True):
        """Remove Text's readings using CG3 grammar at gram_path."""
        if gram_path is None:
            gram_path = RSRC_PATH + 'disambiguator.cg3'
        elif isinstance(gram_path, str):
            pass
        elif isinstance(gram_path, Path):
            gram_path = repr(gram_path)
        else:
            print('Unexpected grammar path. Use str.', file=sys.stderr)
            raise NotImplementedError
        if traces:
            cmd = ['vislcg3', '-t', '-g', gram_path]
        else:
            cmd = ['vislcg3', '-g', gram_path]
        try:
            p = Popen(cmd, stdin=PIPE, stdout=PIPE, universal_newlines=True)
        except FileNotFoundError:
            print('vislcg3 must be installed and be in your '
                  'PATH variable to disambiguate a text.', file=sys.stderr)
            raise FileNotFoundError
        output, error = p.communicate(input=self.CG_str())
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
            old.removed_readings = new.removed_readings  # TODO should be += ?
            old.lemmas = new.lemmas
        self._disambiguated = True

    @staticmethod
    def parse_cg3(stream):
        """Convert cg3 stream into hfst tuples.

        Convert...
        "<полчаса>"
            "час N Msc Inan Sg Gen Count" <W:0.0000000000>
                "пол Num Acc" <W:0.0000000000>
        ;   "час N Msc Inan Sg Gen Count" <W:0.0000000000>
                "пол Num Nom" <W:0.0000000000>
        ...into...
        ('полчаса',
         (('пол+Num+Acc#час+N+Msc+Inan+Sg+Gen+Count', 0.0)),
         (('пол+Num+Nom#час+N+Msc+Inan+Sg+Gen+Count', 0.0)))
        """
        output = []
        readings = []
        rm_readings = []
        for line in stream.split('\n'):
            # print('LINE', line)
            # parse and get state: 0-token, 1-reading, 2+-sub-reading
            try:
                n_tok = re.match('"<((?:.|\")*)>"', line).group(1)
                n_state = 0
                # print('PARSE tok', n_tok)
            except AttributeError:
                try:
                    n_rm, n_tabs, n_lemma, n_tags, n_weight, n_rule = re.match(r'(;)?(\t+)"((?:.|\")*)" (.*?) <W:(.*)> ?(.*)$', line).groups()  # noqa: E501
                except AttributeError:
                    if line:
                        print('WARNING (parse_cg3) unrecognized line:', line,
                              file=sys.stderr)
                    continue
                n_tabs = len(n_tabs)  # used to track state as well
                n_weight = float(n_weight)
                if n_rule:
                    n_rule = f' {n_rule}'
                else:
                    n_rule = ''
                n_state = n_tabs
                # print('PARSE read', n_lemma, n_tags)
            # ================================================================
            # do things based on state
            if n_state == 0:
                # add previous reading to readings
                # append previous Token to output
                try:
                    if not o_rm:
                        readings.append((o_read, o_weight, o_rule))
                    else:
                        rm_readings.append((o_read, o_weight, o_rule))
                    t = Token(o_tok, readings, removed_readings=rm_readings)
                    output.append(t)
                    # print(' '*60, '0\tappend.READ', o_read)
                    # print(' '*60, '0\tappend.TOK', t)
                except NameError:
                    pass
                readings = []
                rm_readings = []
                o_tok, o_state = n_tok, n_state
                del n_tok, n_state
            elif n_state == 1:
                if o_state >= 1:
                    # append previous reading
                    if not o_rm:  # noqa: F821
                        readings.append((o_read, o_weight, o_rule))  # noqa: F821, E501
                    else:
                        rm_readings.append((o_read, o_weight, o_rule))  # noqa: F821, E501
                    # print(' '*60, '1 (1+)\tappend.READ', o_read)
                n_read = f"{n_lemma}+{n_tags.replace(' ', '+')}"
                # print(' '*60, '1\tREAD', n_read)
                # rotate values from new to old
                o_rm, o_tabs, o_lemma, o_tags, o_weight, o_rule, o_read, o_state = n_rm, n_tabs, n_lemma, n_tags, n_weight, n_rule, n_read, n_state  # noqa: E501,F841
                del n_rm, n_tabs, n_lemma, n_tags, n_weight, n_rule, n_read, n_state  # noqa: E501
            else:  # if n_state > 1
                # add subreading to reading
                n_read = f"{n_lemma}+{n_tags.replace(' ', '+')}#{o_read}"
                # print(' '*60, '2\tREAD', n_read)
                # rotate values from new to old
                o_tabs, o_lemma, o_tags, o_weight, o_rule, o_read, o_state = n_tabs, n_lemma, n_tags, n_weight, n_rule, n_read, n_state  # noqa: E501, F841
                del n_rm, n_tabs, n_lemma, n_tags, n_weight, n_rule, n_read, n_state  # noqa: E501
        # print(' '*60, 'FAT LADY', o_read)
        if not o_rm:
            readings.append((o_read, o_weight, o_rule))
        else:
            rm_readings.append((o_read, o_weight, o_rule))
        t = Token(o_tok, readings, removed_readings=rm_readings)
        output.append(t)
        return output

    def stressify(self, selection='safe', guess=False, experiment=None):
        """Text: Return str of running text with stress marked.

        selection  (Applies only to words in the lexicon.)
            safe   -- Only add stress if it is unambiguous.
            freq   -- lemma+reading > lemma > reading
            random -- Randomly choose between specified stress positions.
            all    -- Add stress to all possible specified stress positions.

        guess
            Applies only to out-of-lexicon words. Makes an "intelligent" guess.

        experiment
            1) Remove stress from Token.orig
            2) Save prediction in each Token.stress_predictions[stress_params]
        """
        if experiment is None:
            experiment = self.experiment
        out_text = [t.stressify(disambiguated=self._disambiguated,
                                selection=selection, guess=guess,
                                experiment=experiment)
                    for t in self.Toks]
        return self.respace(out_text)

    def stress_eval(self, stress_params):
        """Text: get dictionary of evaluation metrics of stress predictions."""
        V = 'аэоуыяеёюи'
        counts = Counter(t.stress_predictions[stress_params][1]
                         for t in self.Toks)
        counts['N_ambig'] = len([1 for t in self.Toks
                                 if (t.stress_ambig > 1
                                     and (len(re.findall(f'[{V}]', t.orig))
                                          > 1))])
        return counts

    def stress_preds2tsv(self, path=None, timestamp=True, filename=None):
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
                    context=False):
        """Text: Return str of running text of phonetic transcription.

        selection  (Applies only to words in the lexicon.)
            safe   -- Only add stress if it is unambiguous.
            freq   -- lemma+reading > lemma > reading
            random -- Randomly choose between specified stress positions.
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
            raise NotImplementedError
        out_text = []
        for t in self.Toks:
            out_text.append(t.phoneticize(disambiguated=self._disambiguated,
                                          selection=selection, guess=guess,
                                          experiment=experiment))
        return self.respace(out_text)

    def respace(self, toks):
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
            for match in re.finditer(r'\s+', self.orig):
                raise NotImplementedError(f'Cannot respace {self}.')
        else:
            return unspace_punct(' '.join(toks))