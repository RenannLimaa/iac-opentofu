# Relatório de Benchmark do OpenTofu

## Configuração

* **Provedor Alvo:** `registry.opentofu.org/kreuzwerker/docker` (v4.6.0)
* **Versão do OpenTofu:** 1.12.6
* **Ambiente Host:** Linux x86_64, daemon Docker local
* **Amostragem:** $n = 50$ iterações completas e consecutivas por tipo de ambiente (150 ciclos completos, 900 comandos `tofu` executados, 0 falhas).

---

## Sumário

### Comandos Avaliados
```
init          Prepara o diretório atual para outros comandos
plan          Mostra mudanças necessárias para a configuração
apply         Cria ou atualiza a infraestrutura
destroy       Destrói infraestrutura previamente criada
```

Este benchmark afere as latências completas de ciclo de vida do OpenTofu em três arquétipos de ambiente.

### Tipos de Ambiente

#### Minimal
* **Recursos:**
  * 1 Rede Bridge 
  * 1 Container Alpine 
* **O que afere:** O custo mínimo de invocação do engine, inicialização de plugins, montagem do DAG e chamada às APIs locais de rede e container.

#### Two-Tier
* **Recursos:**
  * 1 Rede Bridge
  * 1 Volume Docker montado em `/usr/share/nginx/html` por ambos os containers.
  * 2 Containers Nginx:
    * `bench-two-tier-backend`: Container de aplicação servindo conteúdo a partir do volume compartilhado.
    * `bench-two-tier-gateway`: Gateway/proxy que expõe a porta `18080` no host e possui dependência explícita `depends_on = [docker_container.backend]`.
* **O que afere:** A capacidade do motor de serializar a criação na ordem correta (`rede` $\to$ `volume` $\to$ `backend` $\to$ `gateway`) e inverter com segurança a ordem na destruição, garantindo que o volume e o backend só sejam removidos após o encerramento do gateway.

#### Multi-Worker
* **Recursos:**
  * **2 Redes Bridge:**
    * Rede pública/de borda.
    * Rede interna privada onde residem os nós de trabalho.
  * 1 Container Ingress (Nginx): exposto na porta `19080` do host e conectado com dual-homing em ambas as redes (`main` e `workers`), atuando como ponte entre o tráfego externo e os workers.
  * 8 Containers Workers (Alpine) conectados exclusivamente à rede interna de workers.
* **O que afere:** Como o escalonador lida com a criação concorrente de 9 containers em paralelo (8 workers + 1 ingress), a resolução de múltiplas interfaces de rede virtuais por container e o impacto no tempo de desmontagem concorrente durante o `destroy`.

### Principais Conclusões
* **Escalabilidade:** Escalar de 1 container (`minimal`) para 9 containers (`multi-worker`) elevou o tempo de criação (`apply`) em apenas **12,2%** (de $2,64\text{s}$ para $2,96\text{s}$), demonstrando a eficiência do escalonador paralelo do grafo (DAG) do OpenTofu sob `-parallelism=10`.
* **Assimetria entre Criação e Destruição:** A destruição (`destroy`) leva consistentemente entre **$1,76\times$ e $1,82\times$ mais tempo** do que a criação em todos os arquétipos ($4,81\text{s}$ a $5,20\text{s}$). O encerramento ordenado de processos via sinal, liberação de interfaces de rede e desconexão de volumes no provedor justificam essa assimetria.
* **Gargalo da Atualização de Estado:** A verificação de grafo puramente em memória (`plan_refresh_false`) executa em $\sim 290\text{ms} - 320\text{ms}$, enquanto a detecção ativa de drift (`plan_refresh_true`) demanda $\sim 2,32\text{s} - 2,34\text{s}$. Aproximadamente 87% do tempo do plano é gasto em I/O de rede e socket com o provedor, e não no cálculo interno do OpenTofu.

---

## Resultados

| Tipo de Ambiente | Fase | Média ($s$) | Desvio Padrão ($s$) | IC 95% Inferior ($s$) | IC 95% Superior ($s$) |
| :--- | :--- | :---: | :---: | :---: | :---: |
| *minimal* | `init` | 0,4814 | 0,1151 | 0,4554 | 0,5177 |
| | `plan_initial` | 0,2907 | 0,0465 | 0,2781 | 0,3037 |
| | **`apply`** | **2,6366** | 0,2313 | **2,5761** | **2,7069** |
| | `plan_refresh_false` | 0,2960 | 0,0480 | 0,2834 | 0,3110 |
| | `plan_refresh_true` | 2,3156 | 0,0464 | 2,3035 | 2,3291 |
| | **`destroy`** | **4,8061** | 0,2071 | **4,7514** | **4,8666** |
| *two-tier* | `init` | 0,4580 | 0,0707 | 0,4442 | 0,4802 |
| | `plan_initial` | 0,2949 | 0,0333 | 0,2857 | 0,3037 |
| | **`apply`** | **2,8482** | 0,1075 | **2,8212** | **2,8802** |
| | `plan_refresh_false` | 0,3181 | 0,0420 | 0,3075 | 0,3294 |
| | `plan_refresh_true` | 2,3437 | 0,0396 | 2,3338 | 2,3544 |
| | **`destroy`** | **4,9525** | 0,0547 | **4,9378** | **4,9673** |
| *multi-worker* | `init` | 0,4491 | 0,0546 | 0,4369 | 0,4660 |
| | `plan_initial` | 0,2775 | 0,0319 | 0,2695 | 0,2867 |
| | **`apply`** | **2,9573** | 0,0930 | **2,9334** | **2,9830** |
| | `plan_refresh_false` | 0,2936 | 0,0294 | 0,2857 | 0,3016 |
| | `plan_refresh_true` | 2,3397 | 0,0264 | 2,3330 | 2,3470 |
| | **`destroy`** | **5,2032** | 0,0554 | **5,1883** | **5,2186** |

---

## Análise de Fases

### init
* Nos três cenários, a inicialização com o provedor previamente cacheado levou entre **$0,43\text{s}$ e $0,48\text{s}$**.
* A pequena variabilidade observada decorre exclusivamente de tempo de criação de processo e leitura de disco.

### plan_initial
* A construção do grafo acíclico dirigido (DAG) antes da existência de recursos demanda entre **$0,28\text{s}$ e $0,30\text{s}$**.
* O cenário `multi-worker` ($0,278\text{s}$) foi ligeiramente mais ágil que o `two-tier` ($0,295\text{s}$) devido ao menor número de regras de dependência cruzada direta (workers em paralelo vs. ordenação estrita com volumes).

### apply
* *minimal*: $2,64\text{s}$ ($95\%\text{ IC: } [2,58\text{s}, 2,71\text{s}]$).
* *two-tier*: $2,85\text{s}$ ($95\%\text{ IC: } [2,82\text{s}, 2,88\text{s}]$).
* *multi-worker*: $2,96\text{s}$ ($95\%\text{ IC: } [2,93\text{s}, 2,98\text{s}]$).
* O paralelismo do OpenTofu mitigou quase todo o custo adicional de criar 8 instâncias adicionais de containers.

### plan_refresh_false vs plan_refresh_true
* `plan -refresh=false`: Valida a configuração contra o estado salvo em memória ($0,29\text{s} - 0,32\text{ s}$).
* `plan -refresh=true`: Consulta o estado em tempo real no socket do Docker daemon ($2,32\text{s} - 2,34\text{s}$).
* A diferença ($\Delta \approx 2,03\text{s}$) evidencia o custo de chamadas remotas para checagem de integridade de recursos.

### destroy
* *minimal*: $4,81\text{s}$
* *two-tier*: $4,95\text{s}$
* *multi-worker*: $5,20\text{s}$