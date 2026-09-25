# Runbook de Kubernetes

## Pod em CrashLoopBackOff

1. `kubectl describe pod NOME -n NAMESPACE` e olhe os eventos.
2. `kubectl logs NOME -n NAMESPACE --previous` para ver o que o pod falou antes de morrer.
3. Causa mais comum: OOMKilled (falta de memoria) ou readiness probe apertada demais.

## Como escalar um deployment

`kubectl scale deployment NOME -n NAMESPACE --replicas=N`.
Em producao, abra mudanca antes. Fora de janela, so com aprovacao do plantao.

## Nodes em NotReady

Olhe `kubectl get nodes` e `kubectl describe node`. Disco cheio em `/var/lib/kubelet` e a
causa mais frequente.
