def check_command_return(ret, msg):
    if ret["returncode"] != 0:
        raise RuntimeError(f"{msg}:\nstdout: {ret['out']}\nstderr: {ret['err']}")