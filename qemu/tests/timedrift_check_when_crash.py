import logging
import time
import re
from autotest.client.shared import error
from autotest.client.shared import utils
from virttest.env_process import preprocess
from virttest.virt_vm import VMDeadKernelCrashError


@error.context_aware
def run(test, params, env):
    """
    Time clock offset check when guest crash/bsod test:

    1) boot guest with '-rtc base=utc,clock=host,driftfix=slew';
    2) sync host system time with "ntpdate clock.redhat.com";
    3) inject nmi to guest/ make linux kernel crash;
    4) sleep long time, then reset vm via system_reset;
    5) query clock offset from ntp server;

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    ntp_server = params.get("ntp_server", "clock.redhat.com")
    ntp_cmd = params["ntp_cmd"]
    ntp_query_cmd = params["ntp_query_cmd"]
    nmi_cmd = params.get("nmi_cmd", "inject-nmi")
    sleep_time = float(params.get("sleep_time", 1800))
    deviation = float(params.get("deviation", 5))

    error.context("sync host time with ntp server", logging.info)
    utils.system("ntpdate %s" % ntp_server)

    error.context("start guest", logging.info)
    params["start_vm"] = "yes"
    preprocess(test, params, env)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    error.context("sync time in guest", logging.info)
    session.cmd(ntp_cmd)

    error.context("inject nmi interrupt in vm", logging.info)
    target, cmd = re.split("\s*:\s*", nmi_cmd)
    if target == "monitor":
        vm.monitor.send_args_cmd(cmd)
    else:
        session.sendline(cmd)
    try:
        session.cmd("dir")
    except Exception:
        pass
    else:
        raise error.TestFail("Guest OS still alive ...")

    error.context("sleep %s seconds" % sleep_time, logging.info)
    time.sleep(sleep_time)
    # Autotest parses serial output and could raise VMDeadKernelCrash
    # we generated using sysrq. Ignore one "BUG:" line
    try:
        session = vm.reboot(method="system_reset")
    except VMDeadKernelCrashError, details:
        details = str(details)
        if (re.findall(r"Trigger a crash\s.*BUG:", details, re.M) and
                details.count("BUG:") != 1):
            raise error.TestFail("Got multiple kernel crashes. Please "
                                 "note that one of them was "
                                 "intentionally  generated by sysrq in "
                                 "this test.\n%s" % details)
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                session = vm.wait_for_login(timeout=timeout)
            except VMDeadKernelCrashError, details:
                details = str(details)
                if (re.findall(r"Trigger a crash\s.*BUG:", details,
                               re.M) and details.count("BUG:") != 1):
                    raise error.TestFail("Got multiple kernel crashes. "
                                         "Please note that one of them was "
                                         "intentionally  generated by sysrq "
                                         "in this test.\n%s" % details)
            else:
                break

    error.context("check time offset via ntp", logging.info)
    output = session.cmd_output(ntp_query_cmd)
    try:
        offset = re.findall(r"[+-](\d+\.\d+)", output, re.M)[-1]
    except IndexError:
        offset = 0.0
    if float(offset) > deviation:
        raise error.TestFail("Unacceptable offset '%s', " % offset +
                             "deviation '%s'" % deviation)
