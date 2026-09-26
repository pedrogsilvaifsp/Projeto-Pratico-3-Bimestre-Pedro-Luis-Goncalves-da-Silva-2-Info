from datetime import datetime
from database import db


class Usuario(db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    usuario = db.Column(db.String(50), unique=True, nullable=False)
    senha_hash = db.Column(db.String(255), nullable=False)
    imagem = db.Column(db.String(255), nullable=True)
    cargo = db.Column(db.String(30), nullable=False, default="gestor_estoque")
    criado_em = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Produto(db.Model):
    __tablename__ = "produtos"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True, nullable=False)
    codigo_barras = db.Column(db.String(50), unique=True, nullable=True)
    preco = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    quantidade = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    custo_total = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    tipo_embalagem = db.Column(db.String(20), nullable=False, default="unidade")
    unidades_por_fardo = db.Column(db.Integer, nullable=False, default=1)
    tipo_venda = db.Column(db.String(20), nullable=False, default="unidade")
    descricao = db.Column(db.Text, nullable=True)
    imagem = db.Column(db.String(255), nullable=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Venda(db.Model):
    __tablename__ = "vendas"

    id = db.Column(db.Integer, primary_key=True)
    valor_total = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    pagamento = db.Column(db.String(30), nullable=False)
    data = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    caixa_id = db.Column(db.Integer, db.ForeignKey("caixas.id", ondelete="SET NULL"), nullable=True)

    itens = db.relationship(
        "ItemVenda",
        back_populates="venda",
        cascade="all, delete-orphan"
    )
    caixa = db.relationship("Caixa", back_populates="vendas")


class ItemVenda(db.Model):
    __tablename__ = "itens_venda"

    id = db.Column(db.Integer, primary_key=True)
    venda_id = db.Column(db.Integer, db.ForeignKey("vendas.id", ondelete="CASCADE"), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey("produtos.id", ondelete="RESTRICT"), nullable=False)
    quantidade = db.Column(db.Numeric(10, 2), nullable=False)
    valor_unitario = db.Column(db.Numeric(10, 2), nullable=False)
    valor_total = db.Column(db.Numeric(10, 2), nullable=False)

    venda = db.relationship("Venda", back_populates="itens")
    produto = db.relationship("Produto")


class Despesa(db.Model):
    __tablename__ = "despesas"

    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(255), nullable=False)
    valor = db.Column(db.Numeric(10, 2), nullable=False)
    data = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    caixa_id = db.Column(db.Integer, db.ForeignKey("caixas.id", ondelete="SET NULL"), nullable=True)

    caixa = db.relationship("Caixa", back_populates="despesas")


class Caixa(db.Model):
    __tablename__ = "caixas"

    id = db.Column(db.Integer, primary_key=True)
    aberto_em = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    fechado_em = db.Column(db.DateTime, nullable=True)
    usuario_abertura_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    usuario_fechamento_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    # Cargo do usuário no momento da abertura.
    # Isso preserva a regra do ranking mesmo que o cargo do usuário seja
    # alterado posteriormente.
    cargo_abertura = db.Column(db.String(30), nullable=True)

    usuario_abertura = db.relationship(
        "Usuario", foreign_keys=[usuario_abertura_id], backref="caixas_abertas"
    )
    usuario_fechamento = db.relationship(
        "Usuario", foreign_keys=[usuario_fechamento_id], backref="caixas_fechados"
    )
    movimentacoes = db.relationship(
        "MovimentacaoCaixa", back_populates="caixa", cascade="all, delete-orphan"
    )
    vendas = db.relationship("Venda", back_populates="caixa")
    despesas = db.relationship("Despesa", back_populates="caixa")

    @property
    def aberto(self):
        return self.fechado_em is None


class MovimentacaoCaixa(db.Model):
    __tablename__ = "movimentacoes_caixa"

    id = db.Column(db.Integer, primary_key=True)
    caixa_id = db.Column(db.Integer, db.ForeignKey("caixas.id", ondelete="SET NULL"), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    tipo = db.Column(db.String(20), nullable=False)
    descricao = db.Column(db.String(255), nullable=True)
    valor = db.Column(db.Numeric(10, 2), nullable=False)
    data = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    caixa = db.relationship("Caixa", back_populates="movimentacoes")
    usuario = db.relationship("Usuario")
