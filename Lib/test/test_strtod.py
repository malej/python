# Tests for the correctly-rounded string -> float conversions
# introduced in Python 2.7 and 3.1.

import random
import struct
import unittest
import re
import sys
from test import test_support

# Correctly rounded str -> float in pure Python, for comparison.

strtod_parser = re.compile(r"""    # A numeric string consists of:
    (?P<sign>[-+])?          # an optional sign, followed by
    (?=\d|\.\d)              # a number with at least one digit
    (?P<int>\d*)             # having a (possibly empty) integer part
    (?:\.(?P<frac>\d*))?     # followed by an optional fractional part
    (?:E(?P<exp>[-+]?\d+))?  # and an optional exponent
    \Z
""", re.VERBOSE | re.IGNORECASE).match

def strtod(s, mant_dig=53, min_exp = -1021, max_exp = 1024):
    """Convert a finite decimal string to a hex string representing an
    IEEE 754 binary64 float.  Return 'inf' or '-inf' on overflow.
    This function makes no use of floating-point arithmetic at any
    stage."""

    # parse string into a pair of integers 'a' and 'b' such that
    # abs(decimal value) = a/b, along with a boolean 'negative'.
    m = strtod_parser(s)
    if m is None:
        raise ValueError('invalid numeric string')
    fraction = m.group('frac') or ''
    intpart = int(m.group('int') + fraction)
    exp = int(m.group('exp') or '0') - len(fraction)
    negative = m.group('sign') == '-'
    a, b = intpart*10**max(exp, 0), 10**max(0, -exp)

    # quick return for zeros
    if not a:
        return '-0x0.0p+0' if negative else '0x0.0p+0'

    # compute exponent e for result; may be one too small in the case
    # that the rounded value of a/b lies in a different binade from a/b
    d = a.bit_length() - b.bit_length()
    d += (a >> d if d >= 0 else a << -d) >= b
    e = max(d, min_exp) - mant_dig

    # approximate a/b by number of the form q * 2**e; adjust e if necessary
    a, b = a << max(-e, 0), b << max(e, 0)
    q, r = divmod(a, b)
    if 2*r > b or 2*r == b and q & 1:
        q += 1
        if q.bit_length() == mant_dig+1:
            q //= 2
            e += 1

    # double check that (q, e) has the right form
    assert q.bit_length() <= mant_dig and e >= min_exp - mant_dig
    assert q.bit_length() == mant_dig or e == min_exp - mant_dig

    # check for overflow and underflow
    if e + q.bit_length() > max_exp:
        return '-inf' if negative else 'inf'
    if not q:
        return '-0x0.0p+0' if negative else '0x0.0p+0'

    # for hex representation, shift so # bits after point is a multiple of 4
    hexdigs = 1 + (mant_dig-2)//4
    shift = 3 - (mant_dig-2)%4
    q, e = q << shift, e - shift
    return '{}0x{:x}.{:0{}x}p{:+d}'.format(
        '-' if negative else '',
        q // 16**hexdigs,
        q % 16**hexdigs,
        hexdigs,
        e + 4*hexdigs)

TEST_SIZE = 10

@unittest.skipUnless(getattr(sys, 'float_repr_style', '') == 'short',
                     "applies only when using short float repr style")
class StrtodTests(unittest.TestCase):
    def check_strtod(self, s):
        """Compare the result of Python's builtin correctly rounded
        string->float conversion (using float) to a pure Python
        correctly rounded string->float implementation.  Fail if the
        two methods give different results."""

        try:
            fs = float(s)
        except OverflowError:
            got = '-inf' if s[0] == '-' else 'inf'
        except MemoryError:
            got = 'memory error'
        else:
            got = fs.hex()
        expected = strtod(s)
        self.assertEqual(expected, got,
                         "Incorrectly rounded str->float conversion for {}: "
                         "expected {}, got {}".format(s, expected, got))

    def test_halfway_cases(self):
        # test halfway cases for the round-half-to-even rule
        for i in xrange(1000):
            for j in xrange(TEST_SIZE):
                # bit pattern for a random finite positive (or +0.0) float
                bits = random.randrange(2047*2**52)

                # convert bit pattern to a number of the form m * 2**e
                e, m = divmod(bits, 2**52)
                if e:
                    m, e = m + 2**52, e - 1
                e -= 1074

                # add 0.5 ulps
                m, e = 2*m + 1, e - 1

                # convert to a decimal string
                if e >= 0:
                    digits = m << e
                    exponent = 0
                else:
                    # m * 2**e = (m * 5**-e) * 10**e
                    digits = m * 5**-e
                    exponent = e
                s = '{}e{}'.format(digits, exponent)
                self.check_strtod(s)

                # get expected answer via struct, to triple check
                #fs = struct.unpack('<d', struct.pack('<Q', bits + (bits&1)))[0]
                #self.assertEqual(fs, float(s))

    def test_boundaries(self):
        # boundaries expressed as triples (n, e, u), where
        # n*10**e is an approximation to the boundary value and
        # u*10**e is 1ulp
        boundaries = [
            (10000000000000000000, -19, 1110),   # a power of 2 boundary (1.0)
            (17976931348623159077, 289, 1995),   # overflow boundary (2.**1024)
            (22250738585072013831, -327, 4941),  # normal/subnormal (2.**-1022)
            (0, -327, 4941),                     # zero
            ]
        for n, e, u in boundaries:
            for j in xrange(1000):
                for i in xrange(TEST_SIZE):
                    digits = n + random.randrange(-3*u, 3*u)
                    exponent = e
                    s = '{}e{}'.format(digits, exponent)
                    self.check_strtod(s)
                n *= 10
                u *= 10
                e -= 1

    def test_underflow_boundary(self):
        # test values close to 2**-1075, the underflow boundary; similar
        # to boundary_tests, except that the random error doesn't scale
        # with n
        for exponent in xrange(-400, -320):
            base = 10**-exponent // 2**1075
            for j in xrange(TEST_SIZE):
                digits = base + random.randrange(-1000, 1000)
                s = '{}e{}'.format(digits, exponent)
                self.check_strtod(s)

    def test_bigcomp(self):
        DIG10 = 10**50
        for i in xrange(1000):
            for j in xrange(TEST_SIZE):
                digits = random.randrange(DIG10)
                exponent = random.randrange(-400, 400)
                s = '{}e{}'.format(digits, exponent)
                self.check_strtod(s)

    def test_parsing(self):
        # make '0' more likely to be chosen than other digits
        digits = '000000123456789'
        signs = ('+', '-', '')

        # put together random short valid strings
        # \d*[.\d*]?e
        for i in xrange(1000):
            for j in xrange(TEST_SIZE):
                s = random.choice(signs)
                intpart_len = random.randrange(5)
                s += ''.join(random.choice(digits) for _ in xrange(intpart_len))
                if random.choice([True, False]):
                    s += '.'
                    fracpart_len = random.randrange(5)
                    s += ''.join(random.choice(digits)
                                 for _ in xrange(fracpart_len))
                else:
                    fracpart_len = 0
                if random.choice([True, False]):
                    s += random.choice(['e', 'E'])
                    s += random.choice(signs)
                    exponent_len = random.randrange(1, 4)
                    s += ''.join(random.choice(digits)
                                 for _ in xrange(exponent_len))

                if intpart_len + fracpart_len:
                    self.check_strtod(s)
                else:
                    try:
                        float(s)
                    except ValueError:
                        pass
                    else:
                        assert False, "expected ValueError"

    def test_particular(self):
        # inputs that produced crashes or incorrectly rounded results with
        # previous versions of dtoa.c, for various reasons
        test_strings = [
            # issue 7632 bug 1, originally reported failing case
            '2183167012312112312312.23538020374420446192e-370',
            # 5 instances of issue 7632 bug 2
            '12579816049008305546974391768996369464963024663104e-357',
            '17489628565202117263145367596028389348922981857013e-357',
            '18487398785991994634182916638542680759613590482273e-357',
            '32002864200581033134358724675198044527469366773928e-358',
            '94393431193180696942841837085033647913224148539854e-358',
            # failing case for bug introduced by METD in r77451 (attempted
            # fix for issue 7632, bug 2), and fixed in r77482.
            '28639097178261763178489759107321392745108491825303e-311',
            # two numbers demonstrating a flaw in the bigcomp 'dig == 0'
            # correction block (issue 7632, bug 3)
            '1.00000000000000001e44',
            '1.0000000000000000100000000000000000000001e44',
            # dtoa.c bug for numbers just smaller than a power of 2 (issue
            # 7632, bug 4)
            '99999999999999994487665465554760717039532578546e-47',
            # failing case for off-by-one error introduced by METD in
            # r77483 (dtoa.c cleanup), fixed in r77490
            '965437176333654931799035513671997118345570045914469' #...
            '6213413350821416312194420007991306908470147322020121018368e0',
            # incorrect lsb detection for round-half-to-even when
            # bc->scale != 0 (issue 7632, bug 6).
            '104308485241983990666713401708072175773165034278685' #...
            '682646111762292409330928739751702404658197872319129' #...
            '036519947435319418387839758990478549477777586673075' #...
            '945844895981012024387992135617064532141489278815239' #...
            '849108105951619997829153633535314849999674266169258' #...
            '928940692239684771590065027025835804863585454872499' #...
            '320500023126142553932654370362024104462255244034053' #...
            '203998964360882487378334860197725139151265590832887' #...
            '433736189468858614521708567646743455601905935595381' #...
            '852723723645799866672558576993978025033590728687206' #...
            '296379801363024094048327273913079612469982585674824' #...
            '156000783167963081616214710691759864332339239688734' #...
            '656548790656486646106983450809073750535624894296242' #...
            '072010195710276073042036425579852459556183541199012' #...
            '652571123898996574563824424330960027873516082763671875e-1075',
            # demonstration that original fix for issue 7632 bug 1 was
            # buggy; the exit condition was too strong
            '247032822920623295e-341',
            # issue 7632 bug 5: the following 2 strings convert differently
            '1000000000000000000000000000000000000000e-16',
            '10000000000000000000000000000000000000000e-17',
            # issue 7632 bug 8:  the following produced 10.0
            '10.900000000000000012345678912345678912345',
            ]
        for s in test_strings:
            self.check_strtod(s)

def test_main():
    test_support.run_unittest(StrtodTests)

if __name__ == "__main__":
    test_main()
