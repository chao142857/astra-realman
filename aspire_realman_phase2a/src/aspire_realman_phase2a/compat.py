"""Narrow Warp 1.9.1 function-registration compatibility, no collision math.

Pinned cuRobo uses the newer wp.func(module=...) API. Warp 1.9.1 already has
the same Function constructor and module/overload machinery but its decorator
does not expose the module argument. This supplies only that registration.
The SDF function objects, code, globals, arguments and gradients are unchanged.
"""
import functools
import inspect


def warp_func(function,*,module,scope):
    import warp as wp
    if 'module' in inspect.signature(wp.func).parameters:
        return wp.func(function,module=module)
    if wp.__version__!='1.9.1':raise RuntimeError('UNREVIEWED_WARP_REGISTRATION_API')
    from warp.context import Function,get_module
    from warp.codegen import make_full_qualified_name
    target=get_module(module);key=make_full_qualified_name(function)
    Function(func=function,key=key,namespace='',module=target,value_func=None,
        scope_locals=scope,doc=(function.__doc__ or '').strip())
    return functools.update_wrapper(target.functions[key],function)
