# Copyright 2019, David Wilson
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its contributors
# may be used to endorse or promote products derived from this software without
# specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""
Mitogen extends Ansible's target configuration mechanism in several ways that
require some care:

* Per-task configurables in Ansible like ansible_python_interpreter are
  connection-layer configurables in Mitogen. They must be extracted during each
  task execution to form the complete connection-layer configuration.

* Mitogen has extra configurables not supported by Ansible at all, such as
  mitogen_ssh_debug_level. These are extracted the same way as
  ansible_python_interpreter.

* Mitogen allows connections to be delegated to other machines. Ansible has no
  internal framework for this, and so Mitogen must figure out a delegated
  connection configuration all on its own. It cannot reuse much of the Ansible
  machinery for building a connection configuration, as that machinery is
  deeply spread out and hard-wired to expect Ansible's usual mode of operation.

For normal and delegate_to connections, Ansible's PlayContext is reused where
possible to maximize compatibility, but for proxy hops, configurations are
built up using the HostVars magic class to call VariableManager.get_vars()
behind the scenes on our behalf. Where Ansible has multiple sources of a
configuration item, for example, ansible_ssh_extra_args, Mitogen must (ideally
perfectly) reproduce how Ansible arrives at its value, without using mechanisms
that are hard-wired or change across Ansible versions.

That is what this file is for. It exports two spec classes, one that takes all
information from PlayContext, and another that takes (almost) all information
from HostVars.
"""

from __future__ import absolute_import, division, print_function
from __future__ import unicode_literals
__metaclass__ = type

import abc
import logging
import os

import ansible.utils.shlex
import ansible.constants as C
import ansible.executor.interpreter_discovery
import ansible.utils.unsafe_proxy

from ansible.module_utils.six import with_metaclass
from ansible.module_utils.parsing.convert_bool import boolean

import mitogen.core


LOG = logging.getLogger(__name__)


def run_interpreter_discovery_if_necessary(s, task_vars, action, rediscover_python):
    """
    Triggers ansible python interpreter discovery if requested.
    Caches this value the same way Ansible does it.
    For connections like `docker`, we want to rediscover the python interpreter because
    it could be different than what's ran on the host
    """
    # keep trying different interpreters until we don't error
    if action._mitogen_discovering_interpreter:
        return action._mitogen_interpreter_candidate

    if s in ['auto', 'auto_legacy', 'auto_silent', 'auto_legacy_silent']:
        # python is the only supported interpreter_name as of Ansible 2.8.8
        interpreter_name = 'python'
        discovered_interpreter_config = u'discovered_interpreter_%s' % interpreter_name

        if task_vars.get('ansible_facts') is None:
           task_vars['ansible_facts'] = {}

        if rediscover_python and task_vars.get('ansible_facts', {}).get(discovered_interpreter_config):
            # if we're rediscovering python then chances are we're running something like a docker connection
            # this will handle scenarios like running a playbook that does stuff + then dynamically creates a docker container,
            # then runs the rest of the playbook inside that container, and then rerunning the playbook again
            action._mitogen_rediscovered_interpreter = True

            # blow away the discovered_interpreter_config cache and rediscover
            del task_vars['ansible_facts'][discovered_interpreter_config]

        if discovered_interpreter_config not in task_vars['ansible_facts']:
            action._mitogen_discovering_interpreter = True
            # fake pipelining so discover_interpreter can be happy
            action._connection.has_pipelining = True
            s = ansible.executor.interpreter_discovery.discover_interpreter(
                action=action,
                interpreter_name=interpreter_name,
                discovery_mode=s,
                task_vars=task_vars,
            )
            s = ansible.utils.unsafe_proxy.AnsibleUnsafeText(s)
            # cache discovered interpreter
            task_vars['ansible_facts'][discovered_interpreter_config] = s
            action._connection.has_pipelining = False
        else:
            s = task_vars['ansible_facts'][discovered_interpreter_config]

        # propagate discovered interpreter as fact
        action._discovered_interpreter_key = discovered_interpreter_config
        action._discovered_interpreter = s

    action._mitogen_discovering_interpreter = False
    return s


def parse_python_path(s, task_vars, action, rediscover_python):
    """
    Given the string set for ansible_python_interpeter, parse it using shell
    syntax and return an appropriate argument vector. If the value detected is
    one of interpreter discovery then run that first. Caches python interpreter
    discovery value in `facts_from_task_vars` like how Ansible handles this.
    """
    if not s:
        # if python_path doesn't exist, default to `auto` and attempt to discover it
        s = 'auto'

    s = run_interpreter_discovery_if_necessary(s, task_vars, action, rediscover_python)
    # if unable to determine python_path, fallback to '/usr/bin/python'
    if not s:
        s = '/usr/bin/python'

    return ansible.utils.shlex.shlex_split(s)


def optional_secret(value):
    """
    Wrap `value` in :class:`mitogen.core.Secret` if it is not :data:`None`,
    otherwise return :data:`None`.
    """
    if value is not None:
        return mitogen.core.Secret(value)


def first_true(it, default=None):
    """
    Return the first truthy element from `it`.
    """
    for elem in it:
        if elem:
            return elem
    return default


class Spec(with_metaclass(abc.ABCMeta, object)):
    """
    A source for variables that comprise a connection configuration.
    """

    @abc.abstractmethod
    def transport(self):
        """
        The name of the Ansible plug-in implementing the connection.
        """

    @abc.abstractmethod
    def inventory_name(self):
        """
        The name of the target being connected to as it appears in Ansible's
        inventory.
        """

    @abc.abstractmethod
    def remote_addr(self):
        """
        The network address of the target, or for container and other special
        targets, some other unique identifier.
        """

    @abc.abstractmethod
    def remote_user(self):
        """
        The username of the login account on the target.
        """

    @abc.abstractmethod
    def password(self):
        """
        The password of the login account on the target.
        """

    @abc.abstractmethod
    def become(self):
        """
        :data:`True` if privilege escalation should be active.
        """

    @abc.abstractmethod
    def become_flags(self):
        """
        The command line arguments passed to the become executable.
        """

    @abc.abstractmethod
    def become_method(self):
        """
        The name of the Ansible become method to use.
        """

    @abc.abstractmethod
    def become_user(self):
        """
        The username of the target account for become.
        """

    @abc.abstractmethod
    def become_pass(self):
        """
        The password of the target account for become.
        """

    @abc.abstractmethod
    def port(self):
        """
        The port of the login service on the target machine.
        """

    @abc.abstractmethod
    def python_path(self):
        """
        Path to the Python interpreter on the target machine.
        """

    @abc.abstractmethod
    def host_key_checking(self):
        """
        Whether or not to check the keys of the target machine
        """

    @abc.abstractmethod
    def private_key_file(self):
        """
        Path to the SSH private key file to use to login.
        """

    @abc.abstractmethod
    def ssh_executable(self):
        """
        Path to the SSH executable.
        """

    @abc.abstractmethod
    def timeout(self):
        """
        The generic timeout for all connections.
        """

    @abc.abstractmethod
    def ansible_ssh_timeout(self):
        """
        The SSH-specific timeout for a connection.
        """

    @abc.abstractmethod
    def ssh_args(self):
        """
        The list of additional arguments that should be included in an SSH
        invocation.
        """

    @abc.abstractmethod
    def become_exe(self):
        """
        The path to the executable implementing the become method on the remote
        machine.
        """

    @abc.abstractmethod
    def sudo_args(self):
        """
        The list of additional arguments that should be included in a sudo
        invocation.
        """

    @abc.abstractmethod
    def mitogen_via(self):
        """
        The value of the mitogen_via= variable for this connection. Indicates
        the connection should be established via an intermediary.
        """

    @abc.abstractmethod
    def mitogen_kind(self):
        """
        The type of container to use with the "setns" transport.
        """

    @abc.abstractmethod
    def mitogen_mask_remote_name(self):
        """
        Specifies whether to set a fixed "remote_name" field. The remote_name
        is the suffix of `argv[0]` for remote interpreters. By default it
        includes identifying information from the local process, which may be
        undesirable in some circumstances.
        """

    @abc.abstractmethod
    def mitogen_buildah_path(self):
        """
        The path to the "buildah" program for the 'buildah' transport.
        """

    @abc.abstractmethod
    def mitogen_docker_path(self):
        """
        The path to the "docker" program for the 'docker' transport.
        """

    @abc.abstractmethod
    def mitogen_kubectl_path(self):
        """
        The path to the "kubectl" program for the 'docker' transport.
        """

    @abc.abstractmethod
    def mitogen_lxc_path(self):
        """
        The path to the "lxc" program for the 'lxd' transport.
        """

    @abc.abstractmethod
    def mitogen_lxc_attach_path(self):
        """
        The path to the "lxc-attach" program for the 'lxc' transport.
        """

    @abc.abstractmethod
    def mitogen_lxc_info_path(self):
        """
        The path to the "lxc-info" program for the 'lxc' transport.
        """

    @abc.abstractmethod
    def mitogen_machinectl_path(self):
        """
        The path to the "machinectl" program for the 'setns' transport.
        """

    @abc.abstractmethod
    def mitogen_podman_path(self):
        """
        The path to the "podman" program for the 'podman' transport.
        """

    @abc.abstractmethod
    def mitogen_ssh_keepalive_interval(self):
        """
        The SSH ServerAliveInterval.
        """

    @abc.abstractmethod
    def mitogen_ssh_keepalive_count(self):
        """
        The SSH ServerAliveCount.
        """

    @abc.abstractmethod
    def mitogen_ssh_debug_level(self):
        """
        The SSH debug level.
        """

    @abc.abstractmethod
    def mitogen_ssh_compression(self):
        """
        Whether SSH compression is enabled.
        """

    @abc.abstractmethod
    def extra_args(self):
        """
        Connection-specific arguments.
        """

    @abc.abstractmethod
    def ansible_doas_exe(self):
        """
        Value of "ansible_doas_exe" variable.
        """

    @abc.abstractmethod
    def verbosity(self):
        """
        How verbose to make logging or diagnostics output.
        """


class PlayContextSpec(Spec):
    """
    PlayContextSpec takes almost all its information as-is from Ansible's
    PlayContext. It is used for normal connections and delegate_to connections,
    and should always be accurate.
    """
    def __init__(self, connection, play_context, transport, inventory_name):
        self._connection = connection
        self._play_context = play_context
        self._transport = transport
        self._inventory_name = inventory_name
        self._task_vars = self._connection._get_task_vars()
        # used to run interpreter discovery
        self._action = connection._action

    def _become_option(self, name):
        plugin = self._connection.become
        try:
            return plugin.get_option(name, self._task_vars, self._play_context)
        except AttributeError:
            # A few ansible_mitogen connection plugins look more like become
            # plugins. They don't quite fit Ansible's plugin.get_option() API.
            # https://github.com/mitogen-hq/mitogen/issues/1173
            fallback_plugins = {'mitogen_doas', 'mitogen_sudo', 'mitogen_su'}
            if self._connection.transport not in fallback_plugins:
                raise

            fallback_options = {
                'become_exe',
                'become_flags',
            }
            if name not in fallback_options:
                raise

            LOG.info(
                'Used fallback=PlayContext.%s for plugin=%r, option=%r',
                name, self._connection, name,
            )
            return getattr(self._play_context, name)

    def _connection_option(self, name, fallback_attr=None):
        try:
            return self._connection.get_option(name, hostvars=self._task_vars)
        except KeyError:
            if fallback_attr is None:
                fallback_attr = name
            LOG.info(
                'Used fallback=PlayContext.%s for plugin=%r, option=%r',
                fallback_attr, self._connection, name,
            )
            return getattr(self._play_context, fallback_attr)

    def transport(self):
        return self._transport

    def inventory_name(self):
        return self._inventory_name

    def remote_addr(self):
        return self._connection_option('host', fallback_attr='remote_addr')

    def remote_user(self):
        return self._connection_option('remote_user')

    def become(self):
        return self._connection.become

    def become_flags(self):
        return self._become_option('become_flags')

    def become_method(self):
        return self._connection.become.name

    def become_user(self):
        return self._become_option('become_user')

    def become_pass(self):
        return optional_secret(self._become_option('become_pass'))

    def password(self):
        return optional_secret(self._connection_option('password'))

    def port(self):
        return self._connection_option('port')

    def python_path(self, rediscover_python=False):
        # See also
        #   - ansible_mitogen.connecton.Connection.get_task_var()
        try:
            delegated_vars = self._task_vars['ansible_delegated_vars']
            variables = delegated_vars[self._connection.delegate_to_hostname]
        except KeyError:
            variables = self._task_vars

        interpreter_python = C.config.get_config_value(
            'INTERPRETER_PYTHON', variables=variables,
        )

        if '{{' in interpreter_python or '{%' in interpreter_python:
            templar = self._connection.templar
            interpreter_python = templar.template(interpreter_python)

        return parse_python_path(
            interpreter_python,
            task_vars=self._task_vars,
            action=self._action,
            rediscover_python=rediscover_python)

    def host_key_checking(self):
        return self._connection_option('host_key_checking')

    def private_key_file(self):
        return self._connection_option('private_key_file')

    def ssh_executable(self):
        return self._connection_option('ssh_executable')

    def timeout(self):
        return self._connection_option('timeout')

    def ansible_ssh_timeout(self):
        return self.timeout()

    def ssh_args(self):
        return [
            mitogen.core.to_text(term)
            for s in (
                self._connection_option('ssh_args'),
                self._connection_option('ssh_common_args'),
                self._connection_option('ssh_extra_args'),
            )
            for term in ansible.utils.shlex.shlex_split(s or '')
        ]

    def become_exe(self):
        return self._become_option('become_exe')

    def sudo_args(self):
        return ansible.utils.shlex.shlex_split(self.become_flags() or '')

    def mitogen_via(self):
        return self._connection.get_task_var('mitogen_via')

    def mitogen_kind(self):
        return self._connection.get_task_var('mitogen_kind')

    def mitogen_mask_remote_name(self):
        return self._connection.get_task_var('mitogen_mask_remote_name')

    def mitogen_buildah_path(self):
        return self._connection.get_task_var('mitogen_buildah_path')

    def mitogen_docker_path(self):
        return self._connection.get_task_var('mitogen_docker_path')

    def mitogen_kubectl_path(self):
        return self._connection.get_task_var('mitogen_kubectl_path')

    def mitogen_lxc_path(self):
        return self._connection.get_task_var('mitogen_lxc_path')

    def mitogen_lxc_attach_path(self):
        return self._connection.get_task_var('mitogen_lxc_attach_path')

    def mitogen_lxc_info_path(self):
        return self._connection.get_task_var('mitogen_lxc_info_path')

    def mitogen_podman_path(self):
        return self._connection.get_task_var('mitogen_podman_path')

    def mitogen_ssh_keepalive_interval(self):
        return self._connection.get_task_var('mitogen_ssh_keepalive_interval')

    def mitogen_ssh_keepalive_count(self):
        return self._connection.get_task_var('mitogen_ssh_keepalive_count')

    def mitogen_machinectl_path(self):
        return self._connection.get_task_var('mitogen_machinectl_path')

    def mitogen_ssh_debug_level(self):
        return self._connection.get_task_var('mitogen_ssh_debug_level')

    def mitogen_ssh_compression(self):
        return self._connection.get_task_var('mitogen_ssh_compression')

    def extra_args(self):
        return self._connection.get_extra_args()

    def ansible_doas_exe(self):
        return (
            self._connection.get_task_var('ansible_doas_exe') or
            os.environ.get('ANSIBLE_DOAS_EXE')
        )

    def verbosity(self):
        try:
            verbosity = self._connection.get_option('verbosity', hostvars=self._task_vars)
        except KeyError:
            verbosity = self.mitogen_ssh_debug_level()

        if verbosity:
            return int(verbosity)

        return 0


class MitogenViaSpec(Spec):
    """
    MitogenViaSpec takes most of its information from the HostVars of the
    running task. HostVars is a lightweight wrapper around VariableManager, so
    it is better to say that VariableManager.get_vars() is the ultimate source
    of MitogenViaSpec's information.

    Due to this, mitogen_via= hosts must have all their configuration
    information represented as host and group variables. We cannot use any
    per-task configuration, as all that data belongs to the real target host.

    Ansible uses all kinds of strange historical logic for calculating
    variables, including making their precedence configurable. MitogenViaSpec
    must ultimately reimplement all of that logic. It is likely that if you are
    having a configruation problem with connection delegation, the answer to
    your problem lies in the method implementations below!
    """
    def __init__(self, inventory_name, host_vars, task_vars, become_method, become_user,
                 play_context, action):
        """
        :param str inventory_name:
            The inventory name of the intermediary machine, i.e. not the target
            machine.
        :param dict host_vars:
            The HostVars magic dictionary provided by Ansible in task_vars.
        :param dict task_vars:
            Task vars provided by Ansible.
        :param str become_method:
            If the mitogen_via= spec included a become method, the method it
            specifies.
        :param str become_user:
            If the mitogen_via= spec included a become user, the user it
            specifies.
        :param PlayContext play_context:
            For some global values **only**, the PlayContext used to describe
            the real target machine. Values from this object are **strictly
            restricted** to values that are Ansible-global, e.g. the passwords
            specified interactively.
        :param ActionModuleMixin action:
            Backref to the ActionModuleMixin required for ansible interpreter discovery
        """
        self._inventory_name = inventory_name
        self._host_vars = host_vars
        self._task_vars = task_vars
        self._become_method = become_method
        self._become_user = become_user
        # Dangerous! You may find a variable you want in this object, but it's
        # almost certainly for the wrong machine!
        self._dangerous_play_context = play_context
        self._action = action

    def transport(self):
        return (
            self._host_vars.get('ansible_connection') or
            C.DEFAULT_TRANSPORT
        )

    def inventory_name(self):
        return self._inventory_name

    def remote_addr(self):
        # play_context.py::MAGIC_VARIABLE_MAPPING
        return (
            self._host_vars.get('ansible_ssh_host') or
            self._host_vars.get('ansible_host') or
            self._inventory_name
        )

    def remote_user(self):
        return (
            self._host_vars.get('ansible_ssh_user') or
            self._host_vars.get('ansible_user') or
            C.DEFAULT_REMOTE_USER
        )

    def become(self):
        return bool(self._become_user)

    def become_flags(self):
        return self._host_vars.get('ansible_become_flags')

    def become_method(self):
        return (
            self._become_method or
            self._host_vars.get('ansible_become_method') or
            C.DEFAULT_BECOME_METHOD
        )

    def become_user(self):
        return self._become_user

    def become_pass(self):
        return optional_secret(
            self._host_vars.get('ansible_become_pass') or
            self._host_vars.get('ansible_become_password')
        )

    def password(self):
        return optional_secret(
            self._host_vars.get('ansible_ssh_password') or
            self._host_vars.get('ansible_ssh_pass') or
            self._host_vars.get('ansible_password')
        )

    def port(self):
        return (
            self._host_vars.get('ansible_ssh_port') or
            self._host_vars.get('ansible_port') or
            C.DEFAULT_REMOTE_PORT
        )

    def python_path(self, rediscover_python=False):
        s = self._host_vars.get('ansible_python_interpreter')
        # #511, #536: executor/module_common.py::_get_shebang() hard-wires
        # "/usr/bin/python" as the default interpreter path if no other
        # interpreter is specified.
        return parse_python_path(
            s,
            task_vars=self._task_vars,
            action=self._action,
            rediscover_python=rediscover_python)

    def host_key_checking(self):
        def candidates():
            yield self._host_vars.get('ansible_ssh_host_key_checking')
            yield self._host_vars.get('ansible_host_key_checking')
            yield C.HOST_KEY_CHECKING
        val = next((v for v in candidates() if v is not None), True)
        return boolean(val)

    def private_key_file(self):
        # TODO: must come from PlayContext too.
        return (
            self._host_vars.get('ansible_ssh_private_key_file') or
            self._host_vars.get('ansible_private_key_file') or
            C.DEFAULT_PRIVATE_KEY_FILE
        )

    def ssh_executable(self):
        return C.config.get_config_value("ssh_executable", plugin_type="connection", plugin_name="ssh", variables=self._task_vars.get("vars", {}))

    def timeout(self):
        # TODO: must come from PlayContext too.
        return C.DEFAULT_TIMEOUT

    def ansible_ssh_timeout(self):
        return (
            self._host_vars.get('ansible_timeout') or
            self._host_vars.get('ansible_ssh_timeout') or
            self.timeout()
        )

    def ssh_args(self):
        local_vars = self._task_vars.get("hostvars", {}).get(self._inventory_name, {})
        return [
            mitogen.core.to_text(term)
            for s in (
                C.config.get_config_value("ssh_args", plugin_type="connection", plugin_name="ssh", variables=local_vars),
                C.config.get_config_value("ssh_common_args", plugin_type="connection", plugin_name="ssh", variables=local_vars),
                C.config.get_config_value("ssh_extra_args", plugin_type="connection", plugin_name="ssh", variables=local_vars)
            )
            for term in ansible.utils.shlex.shlex_split(s)
            if s
        ]

    def become_exe(self):
        return (
            self._host_vars.get('ansible_become_exe') or
            C.DEFAULT_BECOME_EXE
        )

    def sudo_args(self):
        return [
            mitogen.core.to_text(term)
            for s in (
                self._host_vars.get('ansible_sudo_flags') or '',
                self.become_flags() or '',
            )
            for term in ansible.utils.shlex.shlex_split(s)
        ]

    def mitogen_via(self):
        return self._host_vars.get('mitogen_via')

    def mitogen_kind(self):
        return self._host_vars.get('mitogen_kind')

    def mitogen_mask_remote_name(self):
        return self._host_vars.get('mitogen_mask_remote_name')

    def mitogen_buildah_path(self):
        return self._host_vars.get('mitogen_buildah_path')

    def mitogen_docker_path(self):
        return self._host_vars.get('mitogen_docker_path')

    def mitogen_kubectl_path(self):
        return self._host_vars.get('mitogen_kubectl_path')

    def mitogen_lxc_path(self):
        return self._host_vars.get('mitogen_lxc_path')

    def mitogen_lxc_attach_path(self):
        return self._host_vars.get('mitogen_lxc_attach_path')

    def mitogen_lxc_info_path(self):
        return self._host_vars.get('mitogen_lxc_info_path')

    def mitogen_podman_path(self):
        return self._host_vars.get('mitogen_podman_path')

    def mitogen_ssh_keepalive_interval(self):
        return self._host_vars.get('mitogen_ssh_keepalive_interval')

    def mitogen_ssh_keepalive_count(self):
        return self._host_vars.get('mitogen_ssh_keepalive_count')

    def mitogen_machinectl_path(self):
        return self._host_vars.get('mitogen_machinectl_path')

    def mitogen_ssh_debug_level(self):
        return self._host_vars.get('mitogen_ssh_debug_level')

    def mitogen_ssh_compression(self):
        return self._host_vars.get('mitogen_ssh_compression')

    def extra_args(self):
        return []  # TODO

    def ansible_doas_exe(self):
        return (
            self._host_vars.get('ansible_doas_exe') or
            os.environ.get('ANSIBLE_DOAS_EXE')
        )

    def verbosity(self):
        verbosity = self._host_vars.get('ansible_ssh_verbosity')
        if verbosity is None:
            verbosity = self.mitogen_ssh_debug_level()

        if verbosity:
            return int(verbosity)

        return 0
