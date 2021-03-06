import logging
import time
import os

from autotest.client.shared import error

from virttest import utils_misc
from virttest.staging import utils_memory


@error.context_aware
def run(test, params, env):
    """
    KVM restore from file-test:
    1) Pause VM
    2) Save VM to file
    3) Restore VM from file, and measure the time it takes
    4) Remove VM restoration file
    5) Check VM

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    expect_time = int(params.get("expect_restore_time", 25))
    session = vm.wait_for_login(timeout=timeout)

    save_file = params.get("save_file", os.path.join("/tmp",
                                                     utils_misc.generate_random_string(8)))

    try:
        error.context("Pause VM", logging.info)
        vm.pause()

        error.context("Save VM to file", logging.info)
        vm.save_to_file(save_file)

        error.context("Restore VM from file", logging.info)
        time.sleep(10)
        utils_memory.drop_caches()
        vm.restore_from_file(save_file)
        session = vm.wait_for_login(timeout=timeout)
        restore_time = utils_misc.monotonic_time() - vm.start_monotonic_time
        test.write_test_keyval({'result': "%ss" % restore_time})
        logging.info("Restore time: %ss" % restore_time)

    finally:
        try:
            error.context("Remove VM restoration file", logging.info)
            os.remove(save_file)

            error.context("Check VM", logging.info)
            vm.verify_alive()
            vm.wait_for_login(timeout=timeout)
        except Exception:
            logging.warning("Unable to restore VM, restoring from image")
            params["restore_image_after_testing"] = "yes"

    if restore_time > expect_time:
        raise error.TestFail(
            "Guest restoration took too long: %ss" % restore_time)

    session.close()
