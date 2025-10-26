import torch

# Make sure we're using GPU
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Using device:", device)

try:
    # Create a ridiculously large tensor (adjust size to fit your GPU)
    x = torch.randn(1000, 1000, device=device)  # ~32 GB for float32
    y = torch.randn(1000, 1000, device=device)

    # Perform a simple operation that triggers allocation
    z = x @ y.T  # massive matrix multiply

except RuntimeError as e:
    if "out of memory" in str(e):
        print("💥 CUDA Out of Memory Error caught!")
    else:
        raise
