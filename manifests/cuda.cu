// CUDA sample for Part 11 — host-side parse only, no CUDA SDK. The
// declarations below are what clang's CUDA support expects to find in the
// runtime wrapper header; we declare them by hand.

typedef unsigned long size_t;
typedef int cudaError_t;

struct dim3 {
  unsigned x, y, z;
  dim3(unsigned x = 1, unsigned y = 1, unsigned z = 1) : x(x), y(y), z(z) {}
};

typedef struct CUstream_st *cudaStream_t;

// Clang lowers `kernel<<<grid, block>>>(args)` to a call of this function
// (the pre-CUDA-9.2 spelling, which is what clang uses with no SDK found).
extern "C" cudaError_t cudaConfigureCall(dim3 gridDim, dim3 blockDim,
                                         size_t sharedMem = 0,
                                         cudaStream_t stream = 0);

#define __global__ __attribute__((global))
#define __device__ __attribute__((device))
#define __host__ __attribute__((host))
#define __shared__ __attribute__((shared))

__device__ int square(int v) { return v * v; }

__global__ void scale(int *data, int factor) {
  __shared__ int cache[64];
  cache[0] = square(factor);
  data[0] = cache[0];
}

__global__ void fill(int *data) { data[0] = 0; }

__host__ void launch(int *data) {
  scale<<<4, 64>>>(data, 2);
  fill<<<dim3(2, 2), dim3(8, 8), 0>>>(data);
}
