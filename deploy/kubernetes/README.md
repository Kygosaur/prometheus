# Kubernetes deployment

This Kustomize deployment is a future-scale target. Replace the example secret, publish the application image, provide ReadWriteMany storage for company files, install a metrics server, and configure an ingress controller before applying it. Use a managed or separately operated PostgreSQL service for serious production deployments.

The optional `gpu-ollama.yaml` requests one NVIDIA GPU and requires the NVIDIA device plugin. Do not scale it beyond available GPUs. On the current single-GPU workstation keep one model loaded and one parallel generation; horizontally scale API/worker CPU pods independently.
