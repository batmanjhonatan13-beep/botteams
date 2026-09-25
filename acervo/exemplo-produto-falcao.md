# Produto Falcao

O Falcao e o produto de pagamentos. Ele roda no cluster prd-pagamentos, namespace
`pagamentos`.

## Enderecos

- Producao: `10.20.30.40` (balanceador), dominio `falcao.interno.local`
- Homologacao: `10.20.31.7`

## Dono e plantao

Squad Pagamentos. Em crise, acione o time de confiabilidade no canal #sre-plantao.

## Dependencias

Banco `pg-pagamentos`, fila `rabbit-pagamentos`, gateway externo do adquirente.
