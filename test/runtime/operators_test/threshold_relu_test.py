from unittest import SkipTest

import numpy as np

from test.util import generate_kernel_test_case
from webdnn.graph.graph import Graph
from webdnn.graph.operators.threshold_relu import ThresholdRelu
from webdnn.graph.order import OrderNHWC, OrderNCHW
from webdnn.graph.variable import Variable
from webdnn.graph.variables.constant_variable import ConstantVariable

condition_default = {
    "x_order": OrderNHWC,
    "y_order": OrderNHWC,
    "backend": ["webgpu", "webassembly", "fallback"],
    "threshold": 0.5
}


def test_general():
    for condition_custom in [
        {},
        {"threshold": 0},
        {"x_order": OrderNCHW},
    ]:
        condition = dict(condition_default)
        condition.update(condition_custom)

        vx = np.random.rand(2, 3, 4, 5) - 0.5
        vy = vx * (vx > condition["threshold"])

        x = Variable(vx.shape, order=OrderNHWC)
        y, = ThresholdRelu(None, threshold=condition["threshold"])(x)

        x.change_order(condition["x_order"])
        y.change_order(condition["y_order"])

        generate_kernel_test_case(
            description=f"ThresholdRelu: " + (", ".join([f"{k}={v}" for k, v in condition_custom.items()])),
            backend=condition["backend"],
            graph=Graph([x], [y]),
            inputs={x: ConstantVariable(vx, OrderNHWC).change_order(x.order).data},
            expected={y: ConstantVariable(vy, OrderNHWC).change_order(y.order).data},
            raise_skip=False
        )

    raise SkipTest
