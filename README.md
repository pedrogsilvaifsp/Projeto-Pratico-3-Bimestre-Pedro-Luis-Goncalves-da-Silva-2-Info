# Easy Store System

Sistema de gerenciamento de um pequeno mercado desenvolvido em Python com Flask e SQLite.

## Funcionalidades

- Cadastro de produtos;
- Código de barras, preço, estoque e descrição;
- Cadastro e armazenamento seguro de senhas com bcrypt;
- Sistema de cargos: **Root, Gerente, Gestor de Caixa e Gestor de Estoque**;
- Root único, criado na primeira execução quando ainda não existe;
- Controle de permissões diretamente nas rotas e no menu;
- Carrinho de compras;
- Registro de vendas e formas de pagamento;
- Controle de estoque em unidades;
- Registro de despesas e movimentações do caixa;
- Abertura e fechamento do caixa;
- Histórico completo dos períodos de caixa, com usuário de abertura/fechamento e datas;
- Histórico de vendas, despesas e produtos vendidos;
- Cadastro de usuários com cargo e imagem de perfil;
- Exclusão da loja disponível somente para o Root, apagando os dados e reiniciando a configuração;
- Upload de imagens de produtos e usuários.

## Cargos e permissões

| Área / ação | Root | Gerente | Gestor de Caixa | Gestor de Estoque |
|---|---:|---:|---:|---:|
| Visão geral | ✅ | ✅ | ✅ | ✅ |
| Painel | ✅ | ✅ | ❌ | ❌ |
| Estoque | ✅ | ✅ | ❌ | ✅ |
| Despesas | ✅ | ✅ | ❌ | ❌ |
| Usuários | ✅ | ✅ | ❌ | ❌ |
| Histórico de caixa | ✅ | ✅ | ❌ | ❌ |
| Abrir / fechar caixa | ✅ | ✅ | ✅ | ❌ |
| Histórico geral | ✅ | ✅ | ✅ | ✅ |
| Cadastro de produto | ✅ | ✅ | ✅ | ✅ |

> O Gestor de Estoque não recebe as opções de abrir/fechar caixa. O Gestor de Caixa não recebe a aba Estoque. Mesmo que um usuário tente acessar uma URL bloqueada manualmente, o servidor também nega o acesso.

## Primeiro acesso e Root

O sistema **não cria mais um administrador padrão automaticamente**.

Quando o banco ainda não possui um usuário com cargo `root`, a abertura do sistema direciona para a tela **Configuração inicial → Criar Root**.

O Root é único e não pode ser criado pela tela comum de usuários. O primeiro usuário já existente em um banco antigo é automaticamente convertido para Root durante a migração.

Na tela de usuários, o Root não possui botão comum de remoção. O próprio Root recebe a opção **Excluir loja**. A confirmação apaga usuários, produtos, vendas, despesas, movimentações e históricos e, em seguida, o sistema volta para a tela de criação de um novo Root.

## Controle do caixa

O caixa funciona por sessões:

1. Um usuário autorizado abre o caixa.
2. Todas as vendas registradas enquanto ele estiver aberto são vinculadas àquela sessão.
3. As despesas registradas enquanto ele estiver aberto também são vinculadas àquela sessão.
4. Um usuário autorizado fecha o caixa.
5. O histórico conserva o nome do usuário que abriu, o nome do usuário que fechou, a data/hora de abertura, a data/hora de fechamento e as movimentações do período.

Para evitar vendas fora de uma sessão de caixa, o fechamento de compra exige que exista um caixa aberto.

## Tecnologias

- Python 3.11+
- Flask
- Flask-SQLAlchemy
- SQLAlchemy
- SQLite
- bcrypt
- HTML5 e CSS3
- JavaScript
- Chart.js

## Instalação

1. Clone o repositório.
2. Crie um ambiente virtual:

```bash
python -m venv venv
```

3. Ative o ambiente virtual no Windows:

```bash
venv\Scripts\activate
```

4. Instale as dependências:

```bash
pip install -r requirements.txt
```

5. Execute o sistema:

```bash
python app.py
```

O banco `instance/loja.db` e a pasta de uploads são usados automaticamente. Bancos antigos recebem as novas colunas necessárias durante a inicialização, sem apagar os dados existentes.

## Estrutura

```text
easy-store-system/
├── app.py
├── database.py
├── models.py
├── requirements.txt
├── README.md
├── .gitignore
├── instance/
├── static/
│   ├── js/
│   │   └── graficos.js
│   ├── uploads/
│   └── style.css
└── templates/
```
