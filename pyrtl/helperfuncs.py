"""
 Defines a set of helper functions that make constructing hardware easier.

The set of functions includes
as_wires: converts consts to wires if needed (and does nothing to wires)
and_all_bits, or_all_bits, xor_all_bits: apply function across all bits
parity: same as xor_all_bits
mux: generate a multiplexer
concat: concatenate multiple wirevectors into one long vector
get_block: get the block of the arguments, throw error if they are different
"""

import core
import wire
import inspect


# -----------------------------------------------------------------
#        ___       __   ___  __   __
#  |__| |__  |    |__) |__  |__) /__`
#  |  | |___ |___ |    |___ |  \ .__/
#

def as_wires(val, bitwidth=None, truncating=True, block=None):
    """ Return wires from val which may be wires, integers, strings, or bools.

    If the option "truncating" is set to false as_wires will never drop
    bits in doing the conversion -- otherwise it will drop most-significant-bits
    to acheive the desired bitwidth (if one is specified).  This function is used by
    most operations in an attempt to coerce values into WireVectors (for example,
    operations such as "x+1" where "1" needs to be converted to a Const WireVectors.)
    """
    import memory
    block = core.working_block(block)

    if isinstance(val, (int, basestring)):
        # note that this case captures bool as well (as bools are instances of ints)
        return wire.Const(val, bitwidth=bitwidth, block=block)
    elif isinstance(val, memory._MemIndexed):
        # covert to a memory read when the value is actually used
        return val.mem._readaccess(val.index)
    elif not isinstance(val, wire.WireVector):
        raise core.PyrtlError('error, expecting a wirevector, int, or verilog-style const string')
    elif bitwidth == '0':
        raise core.PyrtlError('error, bitwidth must be >= 1')
    elif val.bitwidth is None:
        raise core.PyrtlError('error, attempting to use wirevector with no defined bitwidth')
    elif bitwidth and bitwidth > val.bitwidth:
        return val.zero_extended(bitwidth)
    elif bitwidth and truncating and bitwidth < val.bitwidth:
        return val[:bitwidth]  # truncate the upper bits
    else:
        return val


def and_all_bits(vector):
    """ Returns 1 bit WireVector, the result of "and"ing all bits of the argument vector."""
    return _apply_op_over_all_bits('__and__', vector)


def or_all_bits(vector):
    """ Returns 1 bit WireVector, the result of "or"ing all bits of the argument vector."""
    return _apply_op_over_all_bits('__or__', vector)


def xor_all_bits(vector):
    """ Returns 1 bit WireVector, the result of "xor"ing all bits of the argument vector."""
    return _apply_op_over_all_bits('__xor__', vector)


def parity(vector):
    """ Returns 1 bit WireVector, the result of "xor"ing all bits of the argument vector."""
    return _apply_op_over_all_bits('__xor__', vector)


def _apply_op_over_all_bits(op, vector):
    if len(vector) == 1:
        return vector
    else:
        rest = _apply_op_over_all_bits(op, vector[1:])
        func = getattr(vector[0], op)
        return func(vector[0], rest)


def mux(select, falsecase, truecase, *rest):
    """ Multiplexer returning falsecase for select==0, otherwise truecase.

    :param WireVector select: used as the select input to the multiplexor
    :param WireVector falsecase: the wirevector selected if select==0
    :param WireVector truecase: the wirevector selected if select==1
    :param additional WireVector arguments *rest: wirevectors selected when select>1
    :return: WireVector of length of the longest input (not including select)

    To avoid confusion, if you are using the mux where the select is a "predicate"
    (meaning something that you are checking the truth value of rather than using it
    as a number) it is recommended that you use "falsecase" and "truecase"
    as named arguments because the ordering is different from the classic ternary
    operator of some languages.

    Example of mux as "ternary operator" to take the max of 'a' and 5:
        mux( a<5, truecase=a, falsecase=5)

    Example of mux as "selector" to pick between a0 and a1:
        mux( index, a0, a1 )

    Example of mux as "selector" to pick between a0 ... a3:
        mux( index, a0, a1, a2, a3 )
    """
    block = get_block(select, falsecase, truecase, *rest)
    select = as_wires(select, block=block)
    ins = [falsecase, truecase] + list(rest)

    if 2**len(select) != len(ins):
        raise core.PyrtlError('error, mux select line is %d bits, but selecting from %d inputs' % (len(select), len(ins)))

    if len(select) == 1:
        result = _mux2(select, ins[0], ins[1])
    else:
        half = int(len(ins)/2)
        result = _mux2(select[-1],
                       mux(select[0:-1], *ins[:half]),
                       mux(select[0:-1], *ins[half:]))
    return result


def _mux2(select, falsecase, truecase):
    block = get_block(select, falsecase, truecase)
    select = as_wires(select, block=block)
    a = as_wires(falsecase, block=block)
    b = as_wires(truecase, block=block)

    if len(select) != 1:
        raise core.PyrtlError('error, select input to the mux must be 1-bit wirevector')
    a, b = match_bitwidth(a, b)
    resultlen = len(a)  # both are the same length now

    outwire = wire.WireVector(bitwidth=resultlen, block=block)
    net = core.LogicNet(
        op='x',
        op_param=None,
        args=(select, a, b),
        dests=(outwire,))
    outwire.block.add_net(net)
    return outwire


def get_block(*arglist):
    """ Take any number of wire vector params and return the block they are all in.

    If any of the arguments come from different blocks, throw an error.
    If none of the arguments are wirevectors, return the working_block.
    """
    import memory

    blocks = set()
    for arg in arglist:
        if isinstance(arg, memory._MemIndexed):
            argblock = arg.mem.block
        elif isinstance(arg, wire.WireVector):
            argblock = arg.block
        else:
            argblock = None
        blocks.add(argblock)

    blocks.difference_update({None})  # remove the non block elements

    if len(blocks) > 1:
        raise core.PyrtlError('get_block passed WireVectors from different blocks')
    elif len(blocks):
        block = blocks.pop()
    else:
        block = core.working_block()

    return block


def concat(*args):
    """ Take any number of wire vector params and return a wire vector concatinating them.
    The arguments should be WireVectors (or convertable to WireVectors through as_wires).
    The concatination order places the MSB as arg[0] with less signficant bits following.
    """

    block = get_block(*args)
    if len(args) <= 0:
        raise core.PyrtlError('error, concat requires at least 1 argument')
    if len(args) == 1:
        return as_wires(args[0], block=block)
    else:
        arg_wirevectors = [as_wires(arg, block=block) for arg in args]
        final_width = sum([len(arg) for arg in arg_wirevectors])
        outwire = wire.WireVector(bitwidth=final_width, block=block)
        net = core.LogicNet(
            op='c',
            op_param=None,
            args=tuple(arg_wirevectors),
            dests=(outwire,))
        outwire.block.add_net(net)
        return outwire


def match_bitwidth(*args):
    # TODO: allow for custom bit extension functions
    """ Matches the bitwidth of all of the input arguments
    :type args: WireVector
    :return tuple of args in order with extended bits
    """
    max_len = max(len(wv) for wv in args)
    return (wv.zero_extended(max_len) for wv in args)


def probe(w):
    pname = '(%s)' % w.name
    p = wire.WireVector(name=pname)
    p <<= w


def _get_useful_callpoint_name():
    """ Attempts to find the lowest user-level call into the pyrtl module
    :return (string, int) or None: the file name and line number respectively

    This function walks back the current frame stack attempting to find the 
    first frame that is not part of the pyrtl module.  The filename (stripped
    of path and .py extention) and line number of that call are returned.  
    This point should be the point where the user-level code is making the 
    call to some pyrtl intrisic (for example, calling "mux").   If the 
    attempt to find the callpoint fails for any reason, None is returned.
    """
    loc = None
    frame_stack = inspect.stack()
    try:
        for frame in frame_stack:
            modname = inspect.getmodule(frame[0]).__name__
            if not modname.startswith('pyrtl.'):
                full_filename = frame[0].f_code.co_filename
                filename = full_filename.split('/')[-1].rstrip('.py')
                lineno = frame[0].f_lineno
                loc = (filename, lineno)
                break
    except:
        loc = None
    finally:
        del frame_stack
    return loc
