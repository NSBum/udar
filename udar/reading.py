"""Grammatical readings."""

from math import isclose
import re
from typing import List
from typing import Optional
from typing import Set
from typing import Tuple
from typing import Union

from .fsts import get_fst
from .tag import tag_dict
from .tag import Tag


__all__ = ['Reading', 'MultiReading']

TAB = '\t'


class Reading:
    """Grammatical analysis of a Token.

    A given Token can have many Readings.
    """
    __slots__ = ['_lemma', 'cg_rule', 'L2_tags', 'most_likely', 'tags',
                 'tagset', 'weight']
    _lemma: str
    cg_rule: Optional[str]
    L2_tags: Set[Tag]
    most_likely: bool
    tags: List[Tag]
    tagset: Set[Tag]
    weight: str

    def __init__(self, r: str, weight: str, cg_rule: str):
        """Convert HFST tuples to more user-friendly interface."""
        self.cg_rule = cg_rule
        self._lemma, *tags = re.split(r'\+(?=[^+])', r)  # TODO timeit
        self.tags = [tag_dict[t] for t in tags]
        self.tagset = set(self.tags)
        self.weight = weight
        self.L2_tags = {t for t in self.tags if t.is_L2}
        self.most_likely = False

    @property
    def lemma(self):
        return self._lemma

    def __contains__(self, key: Union[Tag, str]):
        """Enable `in` Reading."""
        return (key == self.lemma
                or key in self.tagset
                or (key in tag_dict
                    and tag_dict[key].ambig_alternative in self.tagset))

    def __iter__(self):
        return (t for t in self.tags)

    def __repr__(self):
        return f'Reading({self.hfst_str()}, {self.weight}, {self.cg_rule})'

    def __str__(self):
        return f'{self.lemma}_{"_".join(t.name for t in self.tags)}'

    def hfst_str(self) -> str:
        """Reading HFST-/XFST-style stream."""
        return f'{self.lemma}+{"+".join(t.name for t in self.tags)}'

    def cg3_str(self, traces=False) -> str:
        """Reading CG3-style stream."""
        if traces:
            rule = self.cg_rule
        else:
            rule = ''
        return f'\t"{self.lemma}" {" ".join(t.name for t in self.tags)} <W:{float(self.weight):.6f}>{rule}'  # noqa: E501

    def hfst_noL2_str(self) -> str:
        """Reading HFST-/XFST-style stream, excluding L2 error tags."""
        return f'{self.lemma}+{"+".join(t.name for t in self.tags if not t.is_L2)}'  # noqa: E501

    def __lt__(self, other: 'Reading'):
        return ((self.lemma, self.tags, float(self.weight), self.cg_rule)
                < (other.lemma, other.tags, float(other.weight), other.cg_rule))  # noqa: E501

    def __eq__(self, other):
        """Matches lemma and all tags."""  # TODO decide about L2, Sem, etc.
        try:
            return (self.lemma == other.lemma
                    and self.tags == other.tags
                    and (self.weight == other.weight
                         or isclose(float(self.weight), float(other.weight),
                                    abs_tol=1e-6))
                    and self.cg_rule == other.cg_rule)
        except AttributeError:
            return False

    def __hash__(self):  # pragma: no cover
        return hash((self.lemma, self.tags, self.weight, self.cg_rule))

    def __len__(self):
        return bool(self.lemma) + len(self.tags)  # TODO wut?

    def generate(self, fst=None) -> Optional[str]:
        """From Reading generate surface form."""
        if fst is None:
            fst = get_fst('generator')
        return fst.generate(self.hfst_noL2_str())

    def replace_tag(self, orig_tag: Union[Tag, str], new_tag: Union[Tag, str]):
        """Replace a given tag in Reading with new tag."""
        # if given tags are `str`s, convert them to `Tag`s.
        # (`Tag`s are mapped to themselves.)
        orig_tag = tag_dict[orig_tag]
        new_tag = tag_dict[new_tag]
        try:
            self.tags[self.tags.index(orig_tag)] = new_tag
            self.tagset = set(self.tags)
        except ValueError:  # orig_tag isn't in self.tags
            pass


class MultiReading(Reading):
    """Complex grammatical analysis of a Token.
    (more than one underlying lemma)
    """
    __slots__ = ['cg_rule', 'most_likely', 'readings', 'weight']
    cg_rule: str
    most_likely: bool
    readings: List['Reading']
    weight: str

    def __init__(self, readings: str, weight: str, cg_rule: str):
        """Convert HFST tuples to more user-friendly interface."""
        # TODO use @property to make the interface of Reading and MultiReading
        # the same. Possibly even merge them into the same object.
        assert '#' in readings
        self.cg_rule = cg_rule
        self.most_likely = False
        self.readings = [_readify((r, weight, cg_rule))  # type: ignore
                         for r in re.findall(r'([^+]*[^#]+)#?', readings)
                         if _readify((r, weight, cg_rule)) is not None]
        self.weight = weight

    def __contains__(self, key: Union[Tag, str]):
        """Enable `in` MultiReading.

        Fastest if `key` is a Tag, but it can also be a str.
        """
        if self.readings:
            return any(key in reading for reading in self.readings)
        else:
            return False

    def __iter__(self):
        """Iterator over *tags* in all readings."""
        return (tag for reading in self.readings for tag in reading)

    def __repr__(self):
        return f'MultiReading({self.hfst_str()}, {self.weight}, {self.cg_rule})'  # noqa: E501

    def __str__(self):
        return f'''{'#'.join(f"""{reading}""" for reading in self.readings)}'''

    def hfst_str(self) -> str:
        """MultiReading HFST-/XFST-style stream."""
        return f'''{'#'.join(f"""{r.hfst_str()}""" for r in self.readings)}'''

    def hfst_noL2_str(self) -> str:
        """MultiReading HFST-/XFST-style stream, excluding L2 error tags."""
        return f'''{'#'.join(f"""{r.hfst_noL2_str()}""" for r in self.readings)}'''  # noqa: E501

    def cg3_str(self, traces=False) -> str:
        """MultiReading CG3-style stream"""
        lines = [f'{TAB * i}{r.cg3_str(traces=traces)}'
                 for i, r in enumerate(reversed(self.readings))]
        return '\n'.join(lines)

    def __lt__(self, other):
        return self.readings < other.readings

    def __eq__(self, other):
        try:
            return (all(s == o for s, o in zip(self.readings, other.readings))
                    and len(self.readings) == len(other.readings))
        except AttributeError:
            return False

    def __hash__(self):  # pragma: no cover
        return hash([(r.lemma, r.tags, r.weight, r.cg_rule)
                     for r in self.readings])

    @property
    def lemma(self) -> str:
        return '_'.join(r.lemma for r in self.readings)

    def generate(self, fst=None) -> str:
        if fst is None:
            fst = get_fst('generator')
        return fst.generate(self.hfst_noL2_str())

    def replace_tag(self, orig_tag: Union[Tag, str], new_tag: Union[Tag, str],
                    which_reading=None):
        """Attempt to replace tag in reading indexed by `which_reading`.
        If which_reading is not supplied, replace tag in all readings.
        """
        # if given tags are `str`s, convert them to `Tag`s.
        # (`Tag`s are mapped to themselves.)
        orig_tag = tag_dict[orig_tag]
        new_tag = tag_dict[new_tag]
        if which_reading is None:
            for r in self.readings:
                try:
                    r.tags[r.tags.index(orig_tag)] = new_tag
                    r.tagset = set(r.tags)
                except ValueError:
                    continue
        else:
            try:
                self.readings[which_reading].tags[self.readings[which_reading].tags.index(orig_tag)] = new_tag  # noqa: E501
            except ValueError:
                pass


def _readify(in_tup: Union[Tuple[str, str], Tuple[str, str, str]]) -> Union['Reading', 'MultiReading', None]:  # noqa: E501
    """Try to make Reading. If that fails, try to make a MultiReading."""
    r, weight, *optional = in_tup
    if isinstance(weight, float):
        weight = f'{weight:.6f}'
    cg_rule: str = optional[0] if optional else ''
    try:
        return Reading(r, weight, cg_rule)
    except KeyError:
        try:
            return MultiReading(r, weight, cg_rule)
        except AssertionError:
            if r.endswith('+?'):
                return None
            else:
                raise NotImplementedError(f'Cannot parse reading {r}.')


def _get_lemmas(reading: Union[Reading, MultiReading]) -> List[str]:
    try:
        return [reading.lemma]
    except AttributeError:  # implies MultiReading
        out = []
        for r in reading.readings:  # type: ignore
            out.extend(_get_lemmas(r))
        return out
