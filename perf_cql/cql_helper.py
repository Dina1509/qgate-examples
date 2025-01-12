import time
from numpy import random
import string


def get_rng_generator(complex_init = True) -> random._generator.Generator:
    """Create generator of random values with initiation"""

    # now and now_ms (as detail about milliseconds)
    now = time.time()
    now_ms = (now - int(now)) * 1000000000

    # calc based on CPU speed
    ns_start = time.perf_counter_ns()
    if complex_init:
        time.sleep(0.01)
        ns_stop = time.perf_counter_ns()

        # create generator with more random seed (now, now_ms, cpu speed)
        return random.default_rng([int(now), int(now_ms), ns_stop - ns_start, ns_stop])
    else:
        return random.default_rng([int(now), int(now_ms), ns_start])


def generate_id(id_size = 4, generator: random._generator.Generator = None):
    """Generate random text sequence

    :param id_size:     size of generated id in charts (default is 4)
    :param generator:   generator for usage, in case of None the new generator will be created
    """
    if not generator:
        generator = get_rng_generator(False)

    sequence = list(string.ascii_lowercase + string.digits)
    return ''.join(generator.choice(sequence) for _ in range(id_size))

def str2bool(value) -> bool:
    """Conversion of text value ("True", "1", "Yes", "On") to Bool value"""
    return value.lower() in ['true', '1', 'yes', 'on']

def read_file(file) -> str:
    with open(file) as f:
        return f.readline()