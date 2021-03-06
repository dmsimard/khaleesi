#!/usr/bin/env python

# -*- coding: utf-8 -*-

# (c) 2014, Gabriele Cerami <gcerami@redhat.com>
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

DOCUMENTATION = '''
---
author: Gabriele Cerami
module: staypuft-deploy-network-step
short_description: Perform Seubnet type to subnets in a deployment
description:
  - ""
version_added: "1.7"
options:
  ip:
    description:
    - The ip of the staypuft host
    required: true
  deployment_id:
    description:
    - The id of the deployment to manage
    required: true
  step:
    description:
    - The step of the deployment to perform
    required: true
  staypuft_session:
    description:
    - A dictionary that contains cookie and token to login to staypuft
    required: true
  typings_map:
    description:
    - A dictionary that maps subnet types to subnets
    required: false
  interface_assignments_map:
    description:
    - A dictionary that maps subnets to hosts in a hostgroup
    required: false
examples:
  vars:
      staypuft_session:
          cookie: "_session_id=77d741976cc72838af15a09d81f19be4"
          token: "/RR4jIElCQhV0YNiE0Jf5+vHHz/q1y3+kHPKQpPhHmg="
      typings_map:
          Tenant: "tenant"
          External: "external"

  tasks:
      - name: assign subnet
        staypuft_subnet_typing:
          ip=10.16.148.31
          deployment_id=6
          staypuft_session="{{ staypuft_session }}"
          typings_map="{{ typings_map}}"
'''

from bs4 import BeautifulSoup
import urllib2, urllib
import ast

class NoRedirectHandler(urllib2.HTTPRedirectHandler):
    def http_error_302(self, req, fp, code, msg, headers):
        infourl = urllib.addinfourl(fp, headers, req.get_full_url())
        infourl.status = code
        infourl.code = code
        return infourl
    http_error_300 = http_error_302
    http_error_301 = http_error_302
    http_error_303 = http_error_302
    http_error_307 = http_error_302

class Staypuft(object):

    def __init__(self, params):
        self.params = params
        self.ip = self.params['ip']
        self.deployment_id = self.params['deployment_id']
        staypuft_session=ast.literal_eval(self.params['staypuft_session'])
        self.staypuft_session_cookie = staypuft_session['cookie']
        self.staypuft_session_token = staypuft_session['token']
        self.step = params['step']

        if self.step == "subnet-typings":
            self.typings_map = ast.literal_eval(self.params['typings_map'])

            self.subnet_map= {}
            self.subnet_type_map = {}
            self.get_subnets()
            self.get_subnets_types()

        if self.step == "gather-ips":

            self.deploy_hostgroups = {}

            self.get_deploy_hostgroups()

        if self.step == "interface-assignments":
            self.interface_assignments_map = ast.literal_eval(self.params['interface_assignments_map'])

            self.deploy_hostgroups = {}
            self.hostgroup_to_hosts_ids_map = {}
            self.subnet_map= {}

            self.get_subnets()
            self.get_deploy_hostgroups()
            self.map_hostgrous_to_hosts_ids()

        if self.step == "associate-discovered-hosts":
            self.associate_hosts_map = ast.literal_eval(self.params['associate_hosts_map'])

            self.deploy_hostgroups = {}
            self.discovered_hosts_ids = []
            self.associate_hosts_id_map = {}

            self.get_deploy_hostgroups()
            self.get_discovered_hosts()
            self.create_associate_hosts_id_map()

    def _url_read(self, url):
        request = urllib2.Request(url)
        request.add_header('Cookie', self.staypuft_session_cookie)
        url_handle = urllib2.urlopen(request)
        return url_handle.read()

    def _url_read_json(self, url):
        parsed_json = json.loads(self._url_read(url))
        return parsed_json

    def _url_read_page(self, url):
        parsed_page = BeautifulSoup(self._url_read(url))
        return parsed_page

    def _url_post(self, url, data):
        request = urllib2.Request(url)
        request.add_header('Cookie', self.staypuft_session_cookie)
        request.add_header('X-CSRF-Token', self.staypuft_session_token)
        request.add_header('Accept', 'text/javascript, application/javascript, application/ecmascript, application/x-ecmascript')
        request.add_data(data)
        url_handle = urllib2.urlopen(request)
        if url_handle.code == 200:
            return True
        return False

    def _url_post_json(self, url, data):
        request = urllib2.Request(url)
        request.add_header('Cookie', self.staypuft_session_cookie)
        request.add_header('X-CSRF-Token', self.staypuft_session_token)
        request.add_header('Accept', 'text/javascript, application/javascript, application/ecmascript, application/x-ecmascript')
        request.add_header('Content-type','application/json')
        request.add_data(data)
        url_handle = urllib2.urlopen(request)
        if url_handle.code == 200 or url_handle.code == 302:
            return True
        return False

    def get_subnets(self):
        response = self._url_read_json("https://%s/api/v2/subnets" % self.ip)
        for result in response['results']:
            self.subnet_map[result['name']] = str(result['id'])

    def get_subnets_types(self):
        parsed_page = self._url_read_page("https://%s/deployments/%s/steps/network_configuration" % (self.ip, self.deployment_id))
        subnet_sections = parsed_page.select("[class~=subnet-type-pull]")
        for subnet_section in subnet_sections:
            self.subnet_type_map[subnet_section.text.replace('\n','').replace('  ','')] = subnet_section['data-subnet-type-id']

    def get_discovered_hosts(self):
        ''' populate discovered_hosts list with host ids of discovered_hosts
        '''
        response = self._url_read_json("https://%s/api/v2/discovered_hosts" % (self.ip))
        for result in response['results']:
            self.discovered_hosts_ids.append(str(result['id']))

    def assign_type_to_subnet(self, subnet_type_id, subnet_id):
        data='subnet_type_id=%s&subnet_id=%s' % (subnet_type_id, subnet_id)
        success = self._url_post("https://%s/subnet_typings?deployment_id=%s" % (self.ip, self.deployment_id), data)
        return success

    def assign_types_to_subnets(self):
        for subnet_type_name, subnet_name in self.typings_map.iteritems():
            subnet_type_id = self.subnet_type_map[subnet_type_name]
            subnet_id = self.subnet_map[subnet_name]
            success = self.assign_type_to_subnet(subnet_type_id, subnet_id)
            if not success:
                return False
        return True

    def get_deploy_hostgroups(self):
        parsed_page = self._url_read_page("https://%s/deployments/%s" % (self.ip, self.deployment_id) )
        for hostgroup_div in parsed_page.select("[class~=form-inline]"):
            hostgroup_name = hostgroup_div.find("label").text
            hostgroup_id = hostgroup_div.find("label")['for']
            self.deploy_hostgroups[hostgroup_name] = str(hostgroup_id)

    def map_hostgrous_to_hosts_ids(self):
        ''' Create a dictionary like this

            Controller (Neutron): [2 ,3, 4]
            Neutron Networker: [5, 6]

            using only the hostgroup present in the deploy
        '''
        for hostgroup_name, hostgroup_id  in self.deploy_hostgroups.iteritems():
            hosts_ids = []
            response = self._url_read_json("https://%s/api/v2/hosts?search=hostgroup_id=%s" % (self.ip, hostgroup_id))
            for result in response['results']:
                hosts_ids.append(result['id'])
            self.hostgroup_to_hosts_ids_map[hostgroup_name] = hosts_ids


    def assign_subnets_to_host_interfaces(self):
        for hostgroup_name, hosts_ids in self.hostgroup_to_hosts_ids_map.iteritems():
            for host_id in hosts_ids:
                if hostgroup_name not in self.interface_assignments_map:
                    hostgroup_name = "Default"
                for interface_name, subnet_name in self.interface_assignments_map[hostgroup_name].iteritems():
                    data="interface=%s" % (interface_name)
                    success = self._url_post("https://%s/deployments/%s/interface_assignments?host_ids=%s&subnet_id=%s" % (self.ip, self.deployment_id, host_id, self.subnet_map[subnet_name]), data )
                    if not success:
                        return False
        return True

    def create_associate_hosts_id_map(self):
        ''' creates a map hostgroup_id -> list of discovered hosts id to assign to it
            by default, if host count is not defined for a partigular hostgroup present on a deploy
            the host count is 1.
        '''
        remaining_discovered_hosts = self.discovered_hosts_ids
        for hostgroup_name, hostgroup_id in self.deploy_hostgroups.iteritems():
            if hostgroup_name in self.associate_hosts_map:
                hosts_count = self.associate_hosts_map[hostgroup_name]
            else:
                hosts_count = 1
            self.associate_hosts_id_map[hostgroup_id] = remaining_discovered_hosts[:hosts_count]
            if hosts_count !=0 and not self.associate_hosts_id_map[hostgroup_id]:
                raise IndexError("not enough discovered hosts to assign to hostgroup")
            remaining_discovered_hosts = remaining_discovered_hosts[hosts_count:]

    def associate_discovered_hosts(self):
        for hostgroup_id, hosts_ids in self.associate_hosts_id_map.iteritems():
            for host_id in hosts_ids:
                data={ "hostgroup_id": hostgroup_id , "host_ids": host_id } #% (hostgroup_id, host_id)
                post_data = json.dumps(data)
                success = self._url_post_json("https://%s/deployments/%s/associate_host" % (self.ip, self.deployment_id), post_data )
                if not success:
                    return False
        return True

    def gather_ips(self):
        parsed_page = self._url_read_page("https://%s/deployments/%s" % (self.ip, self.deployment_id))
        public_api = parsed_page.find(text="Public API:")
        ip_div = public_api.next.next
        ip_p =  ip_div.contents[1]
        public_api_ip = ip_p.text

        id = self.deploy_hostgroups["Generic RHEL 7"]
        api_call = self._url_read_json("https://%s/api/v2/hosts?search=hostgroup_id=%s" % (self.ip, id))
        tempest_ip = api_call["results"][0]["ip"]
        facts = {}
        facts["public_api_ip"] = public_api_ip
        facts["tempest_ip"] = tempest_ip
        return facts

def main():
    module = AnsibleModule(
        argument_spec=dict(
            ip                          =   dict(required=True),
            deployment_id               =   dict(required=True),
            step                        =   dict(required=True),
            staypuft_session            =   dict(required=True),
            typings_map                 =   dict(required=False),
            interface_assignments_map   =   dict(required=False),
            associate_hosts_map         =   dict(required=False),
        )
    )

    step=module.params['step']

    # We will not follow redirects
    opener = urllib2.build_opener(NoRedirectHandler())
    urllib2.install_opener(opener)

    facts = None

    if step == "subnet-typings":
        staypuft_deploy = Staypuft(module.params)
        success = staypuft_deploy.assign_types_to_subnets()
        fail_msg = "unable to assign subnets"

    elif step == "gather-ips":
        staypuft_deploy = Staypuft(module.params)
        facts = staypuft_deploy.gather_ips()
        if facts:
            success = True
        else:
            success = False
        fail_msg = "unable to gather ips"

    elif step == "interface-assignments":
        staypuft_deploy = Staypuft(module.params)
        success = staypuft_deploy.assign_subnets_to_host_interfaces()
        fail_msg = "unable to assign subnets"

    elif step == "associate-discovered-hosts":
        staypuft_deploy = Staypuft(module.params)
        success = staypuft_deploy.associate_discovered_hosts()
        fail_msg = "unable to assign hosts"

    else:
        module.fail_json(msg="unrecognized step: %s" % step)

    if success:
        if facts:
            module.exit_json(changed=True, ansible_facts=facts)
        else:
            module.exit_json(changed=True)
    else:
        module.fail_json(msg=fail_msg)

from ansible.module_utils.basic import *
main()
