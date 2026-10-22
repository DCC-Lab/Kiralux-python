"""Frame decoding and polarimetry: pure numpy, no camera, no PyHardwareLibrary."""
import os

import numpy as np
import pytest

from kiralux.frame import PolarFrame, unpack_mosaic, hsv_to_rgb, HEADER_SIZE, END_TAG, TAG_SIZE

from support import pack_mosaic, frame_bytes, mosaic_from_channels

REAL_CAPTURE = os.path.join(os.path.dirname(__file__), "..", "protocol-analysis", "captures", "raw_big.bin")


# --------------------------------------------------------------------------- #
#  unpack_mosaic
# --------------------------------------------------------------------------- #
class TestUnpackMosaic:
    def test_a_triplet_holds_two_12_bit_pixels(self):
        # known answer, worked by hand: AB CD EF -> 0xDAB, 0xEFC
        data = bytes(52) + END_TAG + bytes(TAG_SIZE - len(END_TAG)) + bytes([0xAB, 0xCD, 0xEF])
        assert unpack_mosaic(data, 2, 1).tolist() == [[0xDAB, 0xEFC]]

    def test_full_size_frame_round_trips(self, frame):
        data, mosaic = frame
        out = unpack_mosaic(data, 2448, 2048)
        assert out.shape == (2048, 2448) and out.dtype == np.uint16
        np.testing.assert_array_equal(out, mosaic)

    def test_pixels_never_exceed_12_bits(self, frame):
        assert unpack_mosaic(frame[0], 2448, 2048).max() <= 4095

    def test_every_packet_gives_up_four_bytes_to_its_header_and_padding(self):
        # 256x256 = 98304 bytes: 16323 in packet 0 (after its tags), then 16380 per packet
        data, mosaic = frame_bytes(256, 256, seed=1)
        assert len(data) == 6 * 16384 + 3 + 81            # packet 0, five full packets, a short last one
        assert data[16384:16387] == bytes([0x90, 0x90, 1])
        np.testing.assert_array_equal(unpack_mosaic(data, 256, 256), mosaic)

    def test_a_frame_shorter_than_a_block_is_a_plain_stream(self):
        data, mosaic = frame_bytes(64, 32, seed=2)
        np.testing.assert_array_equal(unpack_mosaic(data, 64, 32), mosaic)

    def test_truncated_data_is_zero_padded_not_an_error(self):
        data, mosaic = frame_bytes(64, 32, seed=3)
        out = unpack_mosaic(data[: 60 + 300], 64, 32)
        assert out.shape == (32, 64)
        assert (out.ravel()[400:] == 0).all()
        np.testing.assert_array_equal(out.ravel()[:100], mosaic.ravel()[:100])

    def test_accepts_bytes_bytearray_and_memoryview(self):
        data, mosaic = frame_bytes(64, 32, seed=4)
        for kind in (bytes, bytearray, memoryview):
            np.testing.assert_array_equal(unpack_mosaic(kind(data), 64, 32), mosaic)

    @pytest.mark.skipif(not os.path.exists(REAL_CAPTURE), reason="captured frame not in this checkout")
    def test_real_capture_decodes_to_a_smooth_image(self):
        data = open(REAL_CAPTURE, "rb").read()
        m = unpack_mosaic(data, 2448, 2048).astype(int)
        assert m.max() <= 4095
        # same-polarizer neighbours (two rows apart) agree in a real image; scrambled bits would not
        assert np.median(np.abs(m[2:] - m[:-2])) < 200


def test_pack_then_unpack_is_the_identity_on_odd_pixel_counts():
    mosaic = np.arange(15, dtype=np.uint16).reshape(3, 5)
    np.testing.assert_array_equal(unpack_mosaic(pack_mosaic(mosaic), 5, 3), mosaic)


# --------------------------------------------------------------------------- #
#  hsv_to_rgb
# --------------------------------------------------------------------------- #
class TestHsvToRgb:
    @pytest.mark.parametrize("h, rgb", [
        (0.0, (255, 0, 0)), (1 / 6, (255, 255, 0)), (2 / 6, (0, 255, 0)),
        (3 / 6, (0, 255, 255)), (4 / 6, (0, 0, 255)), (5 / 6, (255, 0, 255)),
    ])
    def test_primary_and_secondary_colours(self, h, rgb):
        out = hsv_to_rgb(np.array([h]), np.array([1.0]), np.array([1.0]))
        assert out.dtype == np.uint8
        assert np.abs(out[0].astype(int) - rgb).max() <= 1      # the float -> uint8 cast truncates

    def test_zero_saturation_is_grey_and_zero_value_is_black(self):
        grey = hsv_to_rgb(np.array([0.3]), np.array([0.0]), np.array([0.5]))
        assert len(set(grey[0])) == 1
        assert tuple(hsv_to_rgb(np.array([0.3]), np.array([1.0]), np.array([0.0]))[0]) == (0, 0, 0)

    def test_hue_wraps_around(self):
        a = hsv_to_rgb(np.array([0.25]), np.array([1.0]), np.array([1.0]))
        b = hsv_to_rgb(np.array([1.25]), np.array([1.0]), np.array([1.0]))
        np.testing.assert_array_equal(a, b)

    def test_shape_is_preserved_with_a_trailing_rgb_axis(self):
        h = np.zeros((3, 4))
        assert hsv_to_rgb(h, h, h).shape == (3, 4, 3)


# --------------------------------------------------------------------------- #
#  PolarFrame
# --------------------------------------------------------------------------- #
def uniform(i0, i45, i90, i135, shape=(4, 5)):
    """A PolarFrame whose four analyser images are constant."""
    full = lambda v: np.full(shape, v, np.float32)
    return PolarFrame(mosaic_from_channels(full(i0), full(i45), full(i90), full(i135)))


class TestPolarFrame:
    def test_channels_follow_the_imx250_layout(self):
        mosaic = np.array([[90, 45], [135, 0]], np.uint16)
        i0, i45, i90, i135 = PolarFrame(mosaic).channels
        assert (i0[0, 0], i45[0, 0], i90[0, 0], i135[0, 0]) == (0, 45, 90, 135)

    def test_channels_are_half_resolution(self):
        f = PolarFrame(np.zeros((8, 10), np.uint16))
        assert all(c.shape == (4, 5) for c in f.channels)

    def test_odd_dimensions_drop_the_last_row_and_column(self):
        f = PolarFrame(np.zeros((7, 9), np.uint16))
        assert all(c.shape == (3, 4) for c in f.channels)

    def test_horizontal_light(self):
        f = uniform(1, .5, 0, .5)
        s0, s1, s2 = (x.mean() for x in f.stokes)
        assert (s0, s1, s2) == pytest.approx((1, 1, 0))
        assert f.dolp.mean() == pytest.approx(1)
        assert f.aolp.mean() == pytest.approx(0)

    def test_vertical_light_is_90_degrees(self):
        f = uniform(0, .5, 1, .5)
        assert f.dolp.mean() == pytest.approx(1)
        assert abs(f.aolp.mean()) == pytest.approx(90)

    def test_diagonal_light_is_45_degrees(self):
        f = uniform(.5, 1, .5, 0)
        assert f.dolp.mean() == pytest.approx(1)
        assert f.aolp.mean() == pytest.approx(45)

    def test_anti_diagonal_light_is_minus_45_degrees(self):
        assert uniform(.5, 0, .5, 1).aolp.mean() == pytest.approx(-45)

    def test_unpolarized_light_has_no_dolp(self):
        f = uniform(.25, .25, .25, .25)
        assert f.s0.mean() == pytest.approx(0.5)
        assert f.dolp.mean() == pytest.approx(0)

    def test_dark_frame_does_not_divide_by_zero(self):
        f = uniform(0, 0, 0, 0)
        assert np.isfinite(f.dolp).all() and np.isfinite(f.aolp).all()

    def test_views_are_cached(self):
        f = uniform(1, 1, 1, 1)
        assert f.channels is f.channels and f.stokes is f.stokes

    def test_array_protocol_and_shape_and_repr(self):
        mosaic = np.arange(12, dtype=np.uint16).reshape(3, 4)
        f = PolarFrame(mosaic)
        assert np.asarray(f) is mosaic
        assert np.asarray(f, dtype=np.float32).dtype == np.float32
        assert f.shape == (3, 4)
        assert repr(f) == "<PolarFrame 4x3 uint12>"

    def test_falsecolor_is_an_rgb_image_at_half_resolution(self):
        rng = np.random.default_rng(0)
        f = PolarFrame(rng.integers(0, 4096, (16, 20)).astype(np.uint16))
        fc = f.falsecolor
        assert fc.shape == (8, 10, 3) and fc.dtype == np.uint8

    def test_falsecolor_encodes_hue_aolp_saturation_dolp_value_s0(self):
        # horizontal light (hue 0.5 = cyan) with a brightness ramp
        ramp = np.tile(np.linspace(0.1, 1, 8, dtype=np.float32), (4, 1))
        f = PolarFrame(mosaic_from_channels(ramp, ramp / 2, 0 * ramp, ramp / 2))
        fc = f.falsecolor.astype(int)
        assert (fc[..., 0] == 0).all()                        # cyan: no red
        assert fc[0, -1, 1] > fc[0, 0, 1]                     # value follows S0
        assert (fc[..., 1] == fc[..., 2]).all()               # fully polarized: G == B


class TestRawChannels:
    def test_are_uint16_views_of_the_mosaic_without_a_copy(self):
        mosaic = np.arange(8 * 6, dtype=np.uint16).reshape(8, 6)
        frame = PolarFrame(mosaic)
        for channel in frame.raw_channels:
            assert channel.dtype == np.uint16 and channel.shape == (4, 3)
            assert np.shares_memory(channel, mosaic)

    def test_follow_the_sensor_layout_90_45_135_0(self):
        # super-pixel [ 90  45 / 135  0 ]
        frame = PolarFrame(np.array([[90, 45], [135, 0]], np.uint16))
        i0, i45, i90, i135 = (c[0, 0] for c in frame.raw_channels)
        assert (i0, i45, i90, i135) == (0, 45, 90, 135)

    def test_float_channels_hold_the_same_values(self):
        mosaic = np.random.default_rng(5).integers(0, 4096, (16, 12), dtype=np.uint16)
        frame = PolarFrame(mosaic)
        for raw, converted in zip(frame.raw_channels, frame.channels):
            assert converted.dtype == np.float32
            np.testing.assert_array_equal(converted, raw)
