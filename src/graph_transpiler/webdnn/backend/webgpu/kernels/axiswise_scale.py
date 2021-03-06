from typing import List

from webdnn.backend.code_generator.allocator import MemoryLayout
from webdnn.backend.code_generator.injectors.buffer_injector import BufferInjector
from webdnn.backend.code_generator.injectors.kernel_name_injector import KernelNameInjector
from webdnn.backend.webgpu.generator import WebGPUDescriptorGenerator
from webdnn.backend.webgpu.kernel import Kernel, GPUSize
from webdnn.backend.webgpu.preset_placeholders import MAX_THREADS_PER_THREADGROUP
from webdnn.graph.operators.axiswise_scale import AxiswiseScale
from webdnn.util.misc import mul


@WebGPUDescriptorGenerator.register_handler(AxiswiseScale)
def axiswise_scale(op: AxiswiseScale,
                   memory_layout: MemoryLayout) -> List[Kernel]:
    x = memory_layout[op.inputs["x"]]
    y = memory_layout[op.outputs["y"]]

    if x.variable.order == y.variable.order:
        return axiswise_scale_same_order(op, memory_layout)

    else:
        return axiswise_scale_general(op, memory_layout)


def generate_template_same_order(D1, D3):
    return """
kernel void %%FUNC_NAME%%(device float * %%STATIC_BUFFER%%[[buffer(0)]],
                          device float * %%DYNAMIC_BUFFER%%[[buffer(1)]],
                          const device int * %%META_BUFFER%% [[buffer(2)]],
                          uint index[[thread_position_in_grid]],
                          uint num_threads[[threads_per_grid]])
{
#define FLAG_D1_EQUAL_1 %%FLAG_D1_EQUAL_1%%
#define FLAG_D3_EQUAL_1 %%FLAG_D3_EQUAL_1%%

    const device float *X = %%LOAD_BUFFER(axiswise_scale_X)%%;
    const device float *S = %%LOAD_BUFFER(axiswise_scale_S)%%;
    device float *Y = %%LOAD_BUFFER(axiswise_scale_Y)%%;

#if !OPTIMIZE || !FLAG_D1_EQUAL_1
    const int D1 = %%LOAD_BUFFER(axiswise_scale_D1)%%;
#endif

    const int D2 = %%LOAD_BUFFER(axiswise_scale_D2)%%;

#if !OPTIMIZE || !FLAG_D3_EQUAL_1
    const int D3 = %%LOAD_BUFFER(axiswise_scale_D3)%%;
#endif

#if OPTIMIZE && FLAG_D3_EQUAL_1
    #if OPTIMIZE && FLAG_D1_EQUAL_1
        for (int gid = index; gid < D2; gid += num_threads) {
            const int d2 = gid;
    #else
        for (int gid = index; gid < D1 * D2; gid += num_threads) {
            const int d2 = gid % D2;
    #endif

#else

    #if OPTIMIZE && FLAG_D1_EQUAL_1
        for (int gid = index; gid < D2 * D3; gid += num_threads) {
            const int d2 = gid / D3 % D2;

    #else
        for (int gid = index; gid < D1 * D2 * D3; gid += num_threads) {
            const int d2 = gid / D3 % D2;
    #endif

#endif

        float v = X[gid] * S[d2];

        Y[gid] = v;
    }

#undef FLAG_D1_EQUAL_1
#undef FLAG_D3_EQUAL_1
}
""" \
        .replace("%%FLAG_D1_EQUAL_1%%", "1" if D1 == 1 else "0") \
        .replace("%%FLAG_D3_EQUAL_1%%", "1" if D3 == 1 else "0")


def axiswise_scale_same_order(op: AxiswiseScale,
                              memory_layout: MemoryLayout) -> List[Kernel]:
    x = memory_layout[op.inputs["x"]]
    s = memory_layout[op.inputs["s"]]
    y = memory_layout[op.outputs["y"]]

    target_axis_index = x.variable.order.axes_dict[op.axis]
    D1 = mul(x.variable.shape[:target_axis_index])
    D2 = x.variable.shape[target_axis_index]
    D3 = mul(x.variable.shape[target_axis_index + 1:])

    buffer_injector = BufferInjector()
    buffer_injector.register({
        "axiswise_scale_X": x,
        "axiswise_scale_S": s,
        "axiswise_scale_Y": y,
        "axiswise_scale_D1": D1,
        "axiswise_scale_D2": D2,
        "axiswise_scale_D3": D3
    })

    name_injector = KernelNameInjector(op)

    source = generate_template_same_order(D1, D3)
    source = buffer_injector.inject(source)
    source = name_injector.inject(source)

    kernel = Kernel(
        {name_injector.name: source},
        name_injector.name,
        GPUSize(8, 1, 1),
        GPUSize(MAX_THREADS_PER_THREADGROUP, 1, 1),
        buffer_injector.buffer,
        buffer_injector.unresolved_value_list
    )

    return [kernel]


template_general = """
kernel void %%FUNC_NAME%%(device float * %%STATIC_BUFFER%%[[buffer(0)]],
                          device float * %%DYNAMIC_BUFFER%%[[buffer(1)]],
                          const device int * %%META_BUFFER%% [[buffer(2)]],
                          uint index[[thread_position_in_grid]],
                          uint num_threads[[threads_per_grid]])
{
    const device float *X = %%LOAD_BUFFER(axiswise_scale_X)%%;
    const device float *S = %%LOAD_BUFFER(axiswise_scale_S)%%;
    device float *Y = %%LOAD_BUFFER(axiswise_scale_Y)%%;
    const int D = %%LOAD_BUFFER(axiswise_scale_D)%%;
    const int d_target = %%LOAD_BUFFER(axiswise_scale_d_target)%%;
    const device int *x_shape = %%LOAD_BUFFER(axiswise_scale_x_shape)%%;
    const device int *x_stride_in_y = %%LOAD_BUFFER(axiswise_scale_x_stride_in_y)%%;

    int size = 1;
    for (int d = 0; d < D; d++) size *= x_shape[d];

    int D1 = 1;
    for (int d = 0; d < d_target; d++) D1 *= x_shape[d];

    const int D2 = x_shape[d_target];

    int D3 = 1;
    for (int d = d_target + 1; d < D; d++) D3 *= x_shape[d];

    for (int gid = index; gid < size; gid += num_threads) {

        int y_offset = 0;
        int s = gid;
        for (int d = D - 1; d >= 0; d--) {
            y_offset += x_stride_in_y[d] * (s % x_shape[d]);
            s /= x_shape[d];
        }

        const int d2 = gid / D3 % D2;

        float v = X[gid] * S[d2];

        Y[y_offset] = v;
    }
}
"""


def axiswise_scale_general(op: AxiswiseScale,
                           memory_layout: MemoryLayout) -> List[Kernel]:
    x = memory_layout[op.inputs["x"]]
    s = memory_layout[op.inputs["s"]]
    y = memory_layout[op.outputs["y"]]

    x_shape = x.variable.shape

    y_strides = []
    stride = 1
    for sh in reversed(y.variable.shape):
        y_strides.insert(0, stride)
        stride *= sh

    x_stride_in_y = [y_strides[y.variable.order.axes_dict[axis]] for axis in x.variable.order.axes]

    buffer_injector = BufferInjector()
    buffer_injector.register({
        "axiswise_scale_X": x,
        "axiswise_scale_S": s,
        "axiswise_scale_Y": y,
        "axiswise_scale_D": x.variable.ndim,
        "axiswise_scale_d_target": x.variable.order.axes_dict[op.axis],
        "axiswise_scale_x_shape": x_shape,
        "axiswise_scale_x_stride_in_y": x_stride_in_y,
    })

    name_injector = KernelNameInjector(op)

    source = template_general
    source = buffer_injector.inject(source)
    source = name_injector.inject(source)

    kernel = Kernel(
        {name_injector.name: source},
        name_injector.name,
        GPUSize(8, 1, 1),
        GPUSize(MAX_THREADS_PER_THREADGROUP, 1, 1),
        buffer_injector.buffer,
        buffer_injector.unresolved_value_list
    )

    return [kernel]
