from unittest import SkipTest

import numpy as np

from test.runtime.frontend_test.keras_test.util import keras, KerasConverter
from test.util import generate_kernel_test_case


def test():
    for kwargs in [
        {},
        {"use_bias": False},
        {"activation": None},
        {"use_bias": False, "activation": None}
    ]:
        x = keras.layers.Input((4,))
        y = keras.layers.Dense(8, **kwargs)(x)
        model = keras.models.Model([x], [y])

        vx = np.random.rand(2, 4)
        vy = model.predict(vx, batch_size=2)

        graph = KerasConverter(batch_size=2).convert(model)

        generate_kernel_test_case(
            description="[keras] Dense " + (", ".join([f"{k}={v}" for k, v in kwargs.items()])),
            graph=graph,
            inputs={graph.inputs[0]: vx},
            expected={graph.outputs[0]: vy},
            raise_skip=False
        )

    raise SkipTest
