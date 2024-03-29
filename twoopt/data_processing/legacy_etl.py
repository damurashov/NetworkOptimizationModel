"""

Legacy ETL is a bunch of poorly aligned ad-hoc data-processing utilities. So
there is a need for an additional layer on top of the old data
representation-related entities.

"""


def data_amount_planning_make_legacy_env(data_provider):
    from twoopt.simulation.network_data_flow import _LegacyEnv
    from twoopt.optimization.data_amount_planning import \
        make_data_interface_schema_helper

    data_interface, schema = make_data_interface_schema_helper(data_provider)
    legacy_env = _LegacyEnv(data_interface, schema, data_provider)

    return legacy_env


def data_amount_planning_make_legacy_virt_helper(data_provider):
    from twoopt.linsmat import VirtHelper

    legacy_env = data_amount_planning_make_legacy_env(data_provider)
    legacy_virt_helper = VirtHelper(legacy_env)

    return legacy_virt_helper


def data_amount_planning_make_simulation_constructor(data_provider):
    """
    Legacy simulation constructor is expected to return simulation instance
    from data interface and schema. With the new simulation implementation (
    which is a wrapper over the old one) there is no need for such a
    fine-grained construction process.
    """
    def simulation_constructor(*args, **kwrags):
        from twoopt.simulation.network_data_flow import NetworkDataFlow

        # The new implementation is derived from the legacy one, so those are fully compatible
        return NetworkDataFlow(data_provider=data_provider)

    return simulation_constructor


class StaticVariablesConfigWrapper:
    """

    At the time, storing configs in a set of global variables, and changing
    those variables before starting an optimization seemed like a good
    idea... Don't do that. It's bad.

    """

    def __getattr__(self, item):
        try:
            from config import cfg
        except:
            from twoopt.config import cfg

        return getattr(cfg, item)
