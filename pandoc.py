#!/usr/bin/env python

# Python 2.7 Standard Library
from collections import OrderedDict
import json
import sys

# Third-Party Libraries
import sh

# Non-Python Dependencies
try:
    pandoc = sh.pandoc
    magic, version = sh.pandoc("--version").splitlines()[0].split()
    assert magic == "pandoc"
    assert version.startswith("1.12")
except:
    raise ImportError("cannot find pandoc 1.12")

#
# Metadata
# ------------------------------------------------------------------------------
#

from about_pandoc import *

#
# Pandoc Types
# ------------------------------------------------------------------------------
#

def tree_iter(item, delegate=True):
    "Tree iterator"
    if delegate:
        try: # try delegation first
            _tree_iter = item.iter
        except AttributeError:
            _tree_iter = lambda: tree_iter(item, delegate=False)
        for subitem in _tree_iter():
            yield subitem
    else:                
        yield item
        # do not iterate on strings
        if not isinstance(item, basestring):
            try:
                it = iter(item)
                for subitem in it:
                    for subsubitem in tree_iter(subitem):
                        yield subsubitem
            except TypeError: # non-iterable
                pass

# Remark: in the context of Meta, ordered dicts behave "as expected" during 
#         tree iteration: key-value pairs are produced and their contents are 
#         iterated, so the full tree content is produced.
#         But we do have the classic dict behavior (only keys are produced)
#         if we iterate directly. Is it ok ? Changing the default dict behavior
#         could lead to many surprises ... 
#         Should we derive from OrderedDict (say Map) and implement the tree
#         iteration at that level ? That would probably be saner.

class PandocType(object):
    """
    Pandoc types base class

    Refer to the original [Pandoc Types][] documentation for details.

    [Pandoc Types]: http://hackage.haskell.org/package/pandoc-types
    """
    def __init__(self, *args):
        self.args = list(args) # ensure mutability

    def __iter__(self):
        "Child iterator"
        return iter(self.args)

    # Tree iteration (really do it, don't call us back for its implementation)
    iter = lambda self: tree_iter(self, delegate=False)

    def __json__(self):
        """
        Convert the `PandocType instance` into a native Python structure that 
        may be encoded into text by `json.dumps`.
        """
        k_v_pairs = [("t", type(self).__name__), ("c", to_json(self.args))] 
        return OrderedDict(k_v_pairs)

    def __repr__(self):
        typename = type(self).__name__
        args = ", ".join(repr(arg) for arg in self.args)
        return "{0}({1})".format(typename, args)

def declare_types(type_spec, bases=object, dct={}):
    if not isinstance(bases, (tuple, list)):
        bases = (bases,)
    else:
        bases = tuple(bases)
    for type_spec_ in type_spec.strip().splitlines():
       type_parts = [part.strip() for part in type_spec_.strip().split()] 
       type_name = type_parts[0]
       type_args = " ".join(type_parts[1:])
       list_arg = False
       if type_args.startswith("["):
           count = 0
           for i, char in enumerate(type_args):
               count += (char == "[") - (char == "]")
               if count == 0:
                   break
           list_arg = (i == len(type_args) - 1)
       dct["list_arg"] = list_arg
       globals()[type_name] = type(type_name, bases, dct)

class Pandoc(PandocType):
    def __json__(self):
        meta, blocks = self.args[0], self.args[1]
        return [to_json(meta), [to_json(block) for block in blocks]]
    @staticmethod 
    def read(text):
        return read(text)
    def write(self):
        return write(self)

class Meta(PandocType):
    pass


class unMeta(Meta):
    # unMeta does not follow the json representation with 't' and 'k' keys.
    def __json__(self):
        dct = self.args[0]
        k_v_pairs = [(k, to_json(dct[k])) for k in dct]
        return {"unMeta": OrderedDict(k_v_pairs)}
    # implement key-value pair iteration on ordered dicts.
    def iter(self):
        yield self
        yield self.args[0]
        for k_v_pair in self.args[0].items():
            for item in tree_iter(k_v_pair):
                yield item

class MetaValue(PandocType):
    pass

declare_types(\
"""
MetaMap (Map String MetaValue)
MetaList [MetaValue]	 
MetaBool Bool	 
MetaString String	 
MetaInlines [Inline]	 
MetaBlocks [Block]
""", MetaValue)

class Block(PandocType):
    pass # TODO: make this type (and a buch of others) abstract ?
    # Mmmm but we could have to redefine the constructor in every 
    # derived class. Have a look at ABC ?

declare_types(\
"""
Plain [Inline]
Para [Inline]
CodeBlock Attr String
RawBlock Format String
BlockQuote [Block]
OrderedList ListAttributes [[Block]]
BulletList [[Block]]
DefinitionList [([Inline], [[Block]])]
Header Int Attr [Inline]
HorizontalRule
Table [Inline] [Alignment] [Double] [TableCell] [[TableCell]]
Div Attr [Block]
Null
""", Block)

class Inline(PandocType):
    pass

declare_types(\
"""
Str String
Emph [Inline]	
Strong [Inline]	
Strikeout [Inline]	
Superscript [Inline]	
Subscript [Inline]	
SmallCaps [Inline]	
Quoted QuoteType [Inline]	
Cite [Citation] [Inline]	
Code Attr String	
Space	
LineBreak	
Math MathType String	
RawInline Format String	
Link [Inline] Target	
Image [Inline] Target	
Note [Block]	
Span Attr [Inline]	
""", Inline)

class MathType(PandocType):
    pass

class DisplayMath(MathType):
    pass

class MathInline(MathType):
    pass

#
# Json to Pandoc and Pandoc to Json
# ------------------------------------------------------------------------------
#

def to_pandoc(json):
    def is_doc(item):
        return isinstance(item, list) and \
               len(item) == 2 and \
               isinstance(item[0], dict) and \
               "unMeta" in item[0].keys()
    if is_doc(json):
        return Pandoc(*[to_pandoc(item) for item in json])
    elif isinstance(json, list):
        return [to_pandoc(item) for item in json]
    elif isinstance(json, dict) and "t" in json:
        pandoc_type = eval(json["t"])
        contents = json["c"]
        pandoc_contents = to_pandoc(contents)
        if isinstance(pandoc_contents, list) and not getattr(pandoc_type, "list_arg", False):
            return pandoc_type(*pandoc_contents)
        else:
            return pandoc_type(pandoc_contents)
    elif isinstance(json, dict) and "unMeta" in json:
        dct = json["unMeta"]
        k_v_pairs = [(k, to_pandoc(dct[k])) for k in dct]
        return unMeta(OrderedDict(k_v_pairs))

    else:
        return json
    
def to_json(doc_item):
    if hasattr(doc_item, "__json__"):
        return doc_item.__json__()
    elif isinstance(doc_item, list):
        return [to_json(item) for item in doc_item]
    elif isinstance(doc_item, dict):
        return {key: to_json(doc_item[key]) for key in doc_item}
    else:
        return doc_item

#
# Markdown to Pandoc and Pandoc to Markdown
# ------------------------------------------------------------------------------
#

def read(text):
    """
    Read a markdown text as a Pandoc instance.
    """
    json_text = str(sh.pandoc(read="markdown", write="json", _in=text))
    json_ = json.loads(json_text, object_pairs_hook=OrderedDict)
    return to_pandoc(json_)

def write(doc):
    """
    Write a Pandoc instance as a markdown text.
    """
    json_text = json.dumps(to_json(doc))
    return str(sh.pandoc(read="json", write="markdown", _in=json_text))

#
# Command-Line Interface
# ------------------------------------------------------------------------------
#

if __name__ == "__main__":
    json_ = json.loads(sys.stdin.read(), object_pairs_hook=OrderedDict)
    #print json_
    pandoc = to_pandoc(json_)
    print repr(pandoc)
    #print json.dumps(to_json(pandoc))

