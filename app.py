import os
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from uuid import uuid4

import bcrypt
from flask import Flask, render_template, request, redirect, session, flash, url_for, send_from_directory
from sqlalchemy import text
from werkzeug.utils import secure_filename

from database import db
from models import Usuario, Produto, Venda, ItemVenda, Despesa, MovimentacaoCaixa, Caixa


BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

ROLE_LABELS = {
    "root": "Root",
    "gerente": "Gerente",
    "gestor_caixa": "Gestor de Caixa",
    "gestor_estoque": "Gestor de Estoque",
}

PANEL_ROLES = {"root", "gerente"}
DESPESA_ROLES = {"root", "gerente"}
USUARIO_ROLES = {"root", "gerente"}
HISTORICO_CAIXA_ROLES = {"root", "gerente"}
RANKING_ROLES = {"root", "gerente", "gestor_caixa"}
ESTOQUE_ROLES = {"root", "gerente", "gestor_estoque"}
CAIXA_ROLES = {"root", "gerente", "gestor_caixa"}

INSTANCE_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, instance_path=str(INSTANCE_DIR), template_folder=str(BASE_DIR / "templates"), static_folder=str(BASE_DIR / "static"))
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{INSTANCE_DIR / 'loja.db'}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "connect_args": {"check_same_thread": False}
}

db.init_app(app)


def hash_password(senha):
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_password(senha, senha_hash):
    try:
        return bcrypt.checkpw(senha.encode("utf-8"), senha_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def decimal(value, default=Decimal("0")):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def usuario_atual():
    user_id = session.get("usuario_id")
    if not user_id:
        return None
    return db.session.get(Usuario, user_id)


def cargo_atual():
    usuario = usuario_atual()
    return usuario.cargo if usuario else None


def esta_logado():
    return usuario_atual() is not None


def caixa_atual():
    return Caixa.query.filter_by(fechado_em=None).order_by(Caixa.aberto_em.desc()).first()


def totais_caixa_total():
    """Calcula o caixa acumulado de toda a loja.

    O saldo não é reiniciado quando uma sessão é fechada.
    Entradas = todas as vendas; saídas = todas as despesas.
    """
    entradas = db.session.query(
        db.func.coalesce(db.func.sum(Venda.valor_total), 0)
    ).scalar() or 0

    saidas = db.session.query(
        db.func.coalesce(db.func.sum(Despesa.valor), 0)
    ).scalar() or 0

    entradas = Decimal(str(entradas))
    saidas = Decimal(str(saidas))
    return {
        "entrada": entradas,
        "saida": saidas,
        "saldo": entradas - saidas,
    }


def saldo_caixa_total():
    return totais_caixa_total()["saldo"]


def pode_caixa():
    return cargo_atual() in CAIXA_ROLES


def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def login_required():
    return esta_logado()


def role_required(*roles):
    roles = set(roles)

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not login_required():
                return redirect(url_for("admin_login"))
            if cargo_atual() not in roles:
                flash("Seu cargo não possui acesso a esta área.")
                return redirect(url_for("inicio"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def caixa_required():
    return role_required(*CAIXA_ROLES)


def exigir_caixa_aberto():
    """Impede operações comerciais quando não existe caixa aberto."""
    caixa = caixa_atual()
    if caixa is None:
        flash("O caixa está fechado. Abra o caixa antes de realizar esta operação.")
        return False
    return True


def registrar_despesa_no_caixa(descricao, valor, usuario=None):
    """Registra a despesa e sua respectiva saída no caixa aberto."""
    caixa = caixa_atual()
    if caixa is None:
        return False

    valor = Decimal(str(valor))
    if valor <= 0:
        return False

    usuario_id = usuario.id if usuario else None
    db.session.add(Despesa(descricao=descricao, valor=valor, caixa_id=caixa.id))
    db.session.add(
        MovimentacaoCaixa(
            caixa_id=caixa.id,
            usuario_id=usuario_id,
            tipo="saida",
            descricao=descricao,
            valor=valor,
        )
    )
    return True


def get_carrinho():
    return session.setdefault("carrinho", [])


@app.template_filter("produto_nome")
def produto_nome(produto_id):
    produto = db.session.get(Produto, int(produto_id))
    return produto.nome if produto else "Produto removido"


@app.context_processor
def inject_context():
    usuario = usuario_atual()
    return {
        "usuario_logado": usuario,
        "cargo_atual": usuario.cargo if usuario else None,
        "cargo_label": ROLE_LABELS.get(usuario.cargo, "") if usuario else "",
        "caixa_aberto": caixa_atual(),
        "pode_painel": cargo_atual() in PANEL_ROLES,
        "pode_despesa": cargo_atual() in DESPESA_ROLES,
        "pode_usuarios": cargo_atual() in USUARIO_ROLES,
        "pode_historico_caixa": cargo_atual() in HISTORICO_CAIXA_ROLES,
        "pode_ranking": cargo_atual() in RANKING_ROLES,
        "pode_estoque": cargo_atual() in ESTOQUE_ROLES,
        "pode_caixa": cargo_atual() in CAIXA_ROLES,
        "roles_labels": ROLE_LABELS,
    }


@app.before_request
def exigir_root_inicial():
    # Enquanto a loja ainda não possui Root, nenhuma outra tela administrativa/pública é usada.
    if request.endpoint in {"configurar_root", "static", "uploaded_file"}:
        return None

    try:
        existe_root = Usuario.query.filter_by(cargo="root").first() is not None
    except Exception:
        return None

    if not existe_root:
        session.clear()
        return redirect(url_for("configurar_root"))
    return None


with app.app_context():
    db.create_all()

    # Migrações simples para bancos SQLite já existentes.
    colunas_usuarios = db.session.execute(text("PRAGMA table_info(usuarios)")).fetchall()
    nomes_colunas_usuarios = {coluna[1] for coluna in colunas_usuarios}
    if "imagem" not in nomes_colunas_usuarios:
        db.session.execute(text("ALTER TABLE usuarios ADD COLUMN imagem VARCHAR(255) NULL"))
    if "cargo" not in nomes_colunas_usuarios:
        db.session.execute(text("ALTER TABLE usuarios ADD COLUMN cargo VARCHAR(30) NOT NULL DEFAULT 'gerente'"))
        primeiro_usuario = db.session.execute(text("SELECT id FROM usuarios ORDER BY id LIMIT 1")).fetchone()
        if primeiro_usuario:
            db.session.execute(text("UPDATE usuarios SET cargo = 'root' WHERE id = :id"), {"id": primeiro_usuario[0]})

    colunas_produtos = db.session.execute(text("PRAGMA table_info(produtos)")).fetchall()
    nomes_colunas_produtos = {coluna[1] for coluna in colunas_produtos}
    if "custo_total" not in nomes_colunas_produtos:
        db.session.execute(text("ALTER TABLE produtos ADD COLUMN custo_total NUMERIC(10, 2) NOT NULL DEFAULT 0"))
    if "tipo_embalagem" not in nomes_colunas_produtos:
        db.session.execute(text("ALTER TABLE produtos ADD COLUMN tipo_embalagem VARCHAR(20) NOT NULL DEFAULT 'unidade'"))
    if "unidades_por_fardo" not in nomes_colunas_produtos:
        db.session.execute(text("ALTER TABLE produtos ADD COLUMN unidades_por_fardo INTEGER NOT NULL DEFAULT 1"))
    if "tipo_venda" not in nomes_colunas_produtos:
        db.session.execute(text("ALTER TABLE produtos ADD COLUMN tipo_venda VARCHAR(20) NOT NULL DEFAULT 'unidade'"))

    # Tabelas novas para as sessões de caixa.
    db.create_all()

    colunas_movimentacoes = db.session.execute(text("PRAGMA table_info(movimentacoes_caixa)")).fetchall()
    nomes_colunas_movimentacoes = {coluna[1] for coluna in colunas_movimentacoes}
    if "caixa_id" not in nomes_colunas_movimentacoes:
        db.session.execute(text("ALTER TABLE movimentacoes_caixa ADD COLUMN caixa_id INTEGER NULL"))
    if "usuario_id" not in nomes_colunas_movimentacoes:
        db.session.execute(text("ALTER TABLE movimentacoes_caixa ADD COLUMN usuario_id INTEGER NULL"))

    colunas_caixas = db.session.execute(text("PRAGMA table_info(caixas)")).fetchall()
    nomes_colunas_caixas = {coluna[1] for coluna in colunas_caixas}
    if "cargo_abertura" not in nomes_colunas_caixas:
        db.session.execute(text("ALTER TABLE caixas ADD COLUMN cargo_abertura VARCHAR(30) NULL"))
        db.session.execute(text("""
            UPDATE caixas
            SET cargo_abertura = (
                SELECT cargo FROM usuarios
                WHERE usuarios.id = caixas.usuario_abertura_id
            )
            WHERE cargo_abertura IS NULL
        """))

    colunas_vendas = db.session.execute(text("PRAGMA table_info(vendas)")).fetchall()
    nomes_colunas_vendas = {coluna[1] for coluna in colunas_vendas}
    if "caixa_id" not in nomes_colunas_vendas:
        db.session.execute(text("ALTER TABLE vendas ADD COLUMN caixa_id INTEGER NULL"))

    colunas_despesas = db.session.execute(text("PRAGMA table_info(despesas)")).fetchall()
    nomes_colunas_despesas = {coluna[1] for coluna in colunas_despesas}
    if "caixa_id" not in nomes_colunas_despesas:
        db.session.execute(text("ALTER TABLE despesas ADD COLUMN caixa_id INTEGER NULL"))

    # Nunca deixa existir mais de um Root. Em bancos antigos, o primeiro usuário é o proprietário.
    roots = Usuario.query.filter_by(cargo="root").order_by(Usuario.id).all()
    if len(roots) > 1:
        for extra_root in roots[1:]:
            extra_root.cargo = "gerente"

    db.session.commit()


def abrir_caixa_interno(usuario):
    aberto = caixa_atual()
    if aberto:
        return aberto, False
    caixa = Caixa(
        usuario_abertura_id=usuario.id,
        cargo_abertura=usuario.cargo,
    )
    db.session.add(caixa)
    db.session.commit()
    return caixa, True


def fechar_caixa_interno(usuario):
    caixa = caixa_atual()
    if not caixa:
        return None
    caixa.fechado_em = db.func.now()
    caixa.usuario_fechamento_id = usuario.id
    db.session.commit()
    db.session.refresh(caixa)
    return caixa


def apagar_loja():
    # Apaga todos os dados, mantendo apenas a estrutura vazia para o novo cadastro do Root.
    try:
        MovimentacaoCaixa.query.delete(synchronize_session=False)
        ItemVenda.query.delete(synchronize_session=False)
        Venda.query.delete(synchronize_session=False)
        Despesa.query.delete(synchronize_session=False)
        Caixa.query.delete(synchronize_session=False)
        Produto.query.delete(synchronize_session=False)
        Usuario.query.delete(synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    for arquivo in UPLOAD_DIR.iterdir():
        if arquivo.is_file():
            try:
                arquivo.unlink()
            except OSError:
                pass


@app.route("/configurar-root", methods=["GET", "POST"])
def configurar_root():
    if Usuario.query.filter_by(cargo="root").first():
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        usuario_nome = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "")
        arquivo = request.files.get("imagem")
        imagem = None

        if arquivo and arquivo.filename:
            if not allowed_image(arquivo.filename):
                flash("Formato de imagem inválido. Use PNG, JPG, JPEG, GIF ou WEBP.")
                return redirect(url_for("configurar_root"))
            nome_seguro = secure_filename(arquivo.filename)
            if not nome_seguro:
                flash("Nome de imagem inválido.")
                return redirect(url_for("configurar_root"))
            nome_final = f"root_{uuid4().hex}_{nome_seguro}"
            arquivo.save(UPLOAD_DIR / nome_final)
            imagem = nome_final

        if not nome or not usuario_nome or not senha:
            flash("Nome, usuário e senha são obrigatórios para criar o Root.")
            return redirect(url_for("configurar_root"))

        if Usuario.query.filter_by(usuario=usuario_nome).first():
            flash("Esse usuário já existe.")
            return redirect(url_for("configurar_root"))

        root = Usuario(
            nome=nome,
            usuario=usuario_nome,
            senha_hash=hash_password(senha),
            imagem=imagem,
            cargo="root",
        )
        db.session.add(root)
        db.session.commit()
        flash("Root criado com sucesso. Agora faça login para acessar a loja.")
        return redirect(url_for("admin_login"))

    return render_template("configurar_root.html")


@app.route("/")
def loja():
    produtos = Produto.query.order_by(Produto.nome).all()
    return render_template("index.html", produtos=produtos, carrinho=get_carrinho())


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/add", methods=["POST"])
def add_carrinho():
    produto_id = request.form.get("produto_id", "")
    try:
        produto_id = int(produto_id)
        quantidade_pedida = int(request.form.get("quantidade", "0"))
    except ValueError:
        quantidade_pedida = 0
        produto_id = 0

    produto = db.session.get(Produto, produto_id)
    if not produto or quantidade_pedida <= 0:
        flash("Produto ou quantidade inválida.")
        return redirect(url_for("loja"))

    fator = int(produto.unidades_por_fardo or 1) if produto.tipo_venda == "fardo" else 1
    unidades_pedidas = quantidade_pedida * fator
    estoque = int(produto.quantidade)
    carrinho = get_carrinho()
    atual = sum(i.get("quantidade_unidades", i.get("quantidade", 0)) for i in carrinho if i["produto_id"] == produto.id)

    if atual + unidades_pedidas > estoque:
        flash("Quantidade solicitada maior que o estoque disponível.")
        return redirect(url_for("loja"))

    for item in carrinho:
        if item["produto_id"] == produto.id:
            item["quantidade_unidades"] += unidades_pedidas
            item["quantidade_venda"] += quantidade_pedida
            break
    else:
        carrinho.append({
            "produto_id": produto.id,
            "quantidade_unidades": unidades_pedidas,
            "quantidade_venda": quantidade_pedida,
        })

    session.modified = True
    return redirect(url_for("loja"))


@app.route("/finalizar", methods=["POST"])
def finalizar():
    pagamento = request.form.get("pagamento", "").strip()
    if pagamento not in {"Pix", "Cartão", "Dinheiro"}:
        flash("Forma de pagamento inválida.")
        return redirect(url_for("loja"))

    carrinho = get_carrinho()
    if not carrinho:
        flash("O carrinho está vazio.")
        return redirect(url_for("loja"))

    if not exigir_caixa_aberto():
        return redirect(url_for("loja"))

    caixa = caixa_atual()
    if not caixa:
        flash("O caixa está fechado. Abra o caixa antes de registrar vendas.")
        return redirect(url_for("loja"))

    try:
        itens = []
        valor_total = Decimal("0")
        usuario = usuario_atual()

        for item in carrinho:
            produto = db.session.get(Produto, item["produto_id"])
            quantidade = int(item.get("quantidade_unidades", item.get("quantidade", 0)))

            if not produto or quantidade <= 0 or int(produto.quantidade) < quantidade:
                flash("Estoque insuficiente ou produto não encontrado.")
                return redirect(url_for("loja"))

            valor_item = produto.preco * quantidade
            itens.append((produto, quantidade, valor_item))
            valor_total += valor_item

        venda = Venda(valor_total=valor_total, pagamento=pagamento, caixa_id=caixa.id)
        db.session.add(venda)
        db.session.flush()

        for produto, quantidade, valor_item in itens:
            produto.quantidade -= quantidade
            db.session.add(
                ItemVenda(
                    venda_id=venda.id,
                    produto_id=produto.id,
                    quantidade=quantidade,
                    valor_unitario=produto.preco,
                    valor_total=valor_item,
                )
            )

        db.session.add(
            MovimentacaoCaixa(
                caixa_id=caixa.id,
                usuario_id=usuario.id if usuario else None,
                tipo="entrada",
                descricao=f"Venda #{venda.id}",
                valor=valor_total,
            )
        )

        db.session.commit()
        session["carrinho"] = []
        flash(f"Compra finalizada via {pagamento}.")
    except Exception:
        db.session.rollback()
        flash("Não foi possível finalizar a compra.")

    return redirect(url_for("loja"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        usuario_nome = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "")
        usuario = Usuario.query.filter_by(usuario=usuario_nome).first()

        if usuario and check_password(senha, usuario.senha_hash):
            session.clear()
            session["admin"] = True
            session["usuario_id"] = usuario.id
            session["usuario"] = usuario.usuario
            return redirect(url_for("inicio"))

        flash("Usuário ou senha inválidos.")

    return render_template("admin_login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logout realizado.")
    return redirect(url_for("loja"))


@app.route("/admin")
@role_required(*PANEL_ROLES)
def admin():
    produtos = Produto.query.order_by(Produto.nome).all()
    vendas = Venda.query.order_by(Venda.data.desc()).all()
    produtos_vendidos = {}
    for venda in vendas:
        for item in venda.itens:
            nome = item.produto.nome
            produtos_vendidos[nome] = produtos_vendidos.get(nome, 0) + float(item.quantidade)

    return render_template("admin.html", produtos=produtos, vendas=vendas, produtos_vendidos=produtos_vendidos)


@app.route("/inicio")
@role_required("root", "gerente", "gestor_caixa", "gestor_estoque")
def inicio():
    # O saldo do caixa é acumulado de toda a loja. Abrir/fechar cria apenas uma sessão.
    caixa = saldo_caixa_total()

    produtos = Produto.query.order_by(Produto.nome).all()
    vendas = Venda.query.order_by(Venda.data.desc()).all()
    estoque_baixo = sum(1 for produto in produtos if int(produto.quantidade or 0) <= 5)

    return render_template(
        "inicio.html",
        caixa=caixa,
        produtos=produtos,
        vendas=vendas,
        estoque_baixo=estoque_baixo,
    )


@app.route("/produto", methods=["GET", "POST"])
@role_required(*ESTOQUE_ROLES)
def produto():
    if request.method == "POST":
        if not exigir_caixa_aberto():
            return redirect(url_for("produto"))

        nome = request.form.get("nome", "").strip()
        preco = decimal(request.form.get("preco", "0"), Decimal("-1"))
        quantidade = decimal(request.form.get("quantidade", "0"), Decimal("-1"))
        custo_fornecedor = decimal(request.form.get("custo_fornecedor", "0"), Decimal("-1"))
        tipo_embalagem = request.form.get("tipo_embalagem", "unidade").strip().lower()
        unidades_por_fardo = int(request.form.get("unidades_por_fardo", "1") or "1")
        tipo_venda = request.form.get("tipo_venda", "unidade").strip().lower()
        descricao = request.form.get("descricao", "").strip()
        codigo_barras = request.form.get("codigo_barras", "").strip() or None
        arquivo = request.files.get("imagem")
        imagem = None

        if arquivo and arquivo.filename:
            if not allowed_image(arquivo.filename):
                flash("Formato de imagem inválido. Use PNG, JPG, JPEG, GIF ou WEBP.")
                return redirect(url_for("produto"))
            nome_seguro = secure_filename(arquivo.filename)
            if not nome_seguro:
                flash("Nome de imagem inválido.")
                return redirect(url_for("produto"))
            nome_final = f"{uuid4().hex}_{nome_seguro}"
            arquivo.save(UPLOAD_DIR / nome_final)
            imagem = nome_final

        if (not nome or preco < 0 or quantidade < 0 or custo_fornecedor < 0
                or tipo_embalagem not in {"unidade", "fardo"}
                or tipo_venda not in {"unidade", "fardo"}
                or unidades_por_fardo < 1):
            flash("Verifique os dados do produto.")
            return redirect(url_for("produto"))

        if Produto.query.filter_by(nome=nome).first():
            flash("Esse produto já existe.")
            return redirect(url_for("produto"))

        if codigo_barras and Produto.query.filter_by(codigo_barras=codigo_barras).first():
            flash("Esse código de barras já existe.")
            return redirect(url_for("produto"))

        unidades_finais = quantidade * unidades_por_fardo if tipo_embalagem == "fardo" else quantidade
        unidades_por_fardo_final = unidades_por_fardo if (tipo_embalagem == "fardo" or tipo_venda == "fardo") else 1

        produto_obj = Produto(
            nome=nome,
            codigo_barras=codigo_barras,
            preco=preco,
            quantidade=unidades_finais,
            custo_total=custo_fornecedor,
            tipo_embalagem=tipo_embalagem,
            unidades_por_fardo=unidades_por_fardo_final,
            tipo_venda=tipo_venda,
            descricao=descricao,
            imagem=imagem,
        )
        db.session.add(produto_obj)
        db.session.flush()

        # A quantidade inicial representa uma entrada de compra.
        # O custo é calculado pelo preço cadastrado do fornecedor x quantidade de compra.
        if quantidade > 0 and custo_fornecedor > 0:
            descricao_despesa = f"Compra inicial do fornecedor - {nome}"
            valor_despesa = custo_fornecedor * quantidade
            if not registrar_despesa_no_caixa(descricao_despesa, valor_despesa, usuario_atual()):
                db.session.rollback()
                flash("O caixa está fechado. Abra o caixa antes de cadastrar o estoque inicial do produto.")
                return redirect(url_for("produto"))

        db.session.commit()
        flash("Produto cadastrado com sucesso! O custo inicial do fornecedor foi contabilizado nas despesas.")
        return redirect(url_for("produto"))

    return render_template("produto.html")


@app.route("/comprar-produto", methods=["GET", "POST"])
@role_required(*ESTOQUE_ROLES)
def comprar_produto():
    codigo_barras = request.args.get("codigo_barras", "").strip()
    if request.method == "POST":
        if not exigir_caixa_aberto():
            return redirect(url_for("comprar_produto", codigo_barras=codigo_barras))

        produto_id = request.form.get("produto_id", "")
        try:
            produto_id = int(produto_id)
        except (TypeError, ValueError):
            produto_id = 0

        produto = db.session.get(Produto, produto_id)
        quantidade_compra = decimal(request.form.get("quantidade_compra", "0"), Decimal("-1"))

        if not produto:
            flash("Produto não encontrado.")
            return redirect(url_for("comprar_produto"))
        if quantidade_compra <= 0 or quantidade_compra != quantidade_compra.to_integral_value():
            flash("Informe uma quantidade inteira válida para a compra.")
            return redirect(url_for("comprar_produto", codigo_barras=produto.codigo_barras or ""))

        quantidade_compra = quantidade_compra.to_integral_value()
        fator = Decimal(str(produto.unidades_por_fardo or 1)) if produto.tipo_embalagem == "fardo" else Decimal("1")
        unidades_adicionadas = quantidade_compra * fator
        preco_fornecedor = Decimal(str(produto.custo_total or 0))
        valor_total = preco_fornecedor * quantidade_compra

        if preco_fornecedor <= 0:
            flash("O produto não possui um preço de fornecedor cadastrado. Edite o produto antes de comprar.")
            return redirect(url_for("comprar_produto", codigo_barras=produto.codigo_barras or ""))

        try:
            produto.quantidade = Decimal(str(produto.quantidade or 0)) + unidades_adicionadas
            if not registrar_despesa_no_caixa(
                f"Compra de fornecedor - {produto.nome}",
                valor_total,
                usuario_atual(),
            ):
                db.session.rollback()
                flash("O caixa está fechado. Abra o caixa antes de comprar produtos.")
                return redirect(url_for("comprar_produto", codigo_barras=produto.codigo_barras or ""))

            db.session.commit()
            unidade_label = "fardo(s)" if produto.tipo_embalagem == "fardo" else "unidade(s)"
            flash(f"Compra registrada: {int(quantidade_compra)} {unidade_label}. Estoque atualizado em {int(unidades_adicionadas)} unidade(s). Total do fornecedor: R$ {valor_total:.2f}.")
        except Exception:
            db.session.rollback()
            flash("Não foi possível registrar a compra.")

        return redirect(url_for("comprar_produto", codigo_barras=produto.codigo_barras or ""))

    produto = None
    if codigo_barras:
        produto = Produto.query.filter_by(codigo_barras=codigo_barras).first()
        if not produto:
            flash("Produto não encontrado para este código de barras.")

    produtos = Produto.query.order_by(Produto.nome).all()
    return render_template("comprar_produto.html", produto=produto, codigo_barras=codigo_barras, produtos=produtos)


@app.route("/despesa", methods=["GET", "POST"])
@role_required(*DESPESA_ROLES)
def despesa():
    if request.method == "POST":
        if not exigir_caixa_aberto():
            return redirect(url_for("despesa"))

        descricao = request.form.get("descricao", "").strip()
        valor = decimal(request.form.get("valor", "0"))

        if not descricao or valor <= 0:
            flash("Descrição e valor válidos são obrigatórios.")
            return redirect(url_for("despesa"))

        if not registrar_despesa_no_caixa(descricao, valor, usuario_atual()):
            flash("O caixa está fechado. Abra o caixa antes de registrar uma despesa.")
            return redirect(url_for("despesa"))

        db.session.commit()
        flash("Despesa registrada!")
        return redirect(url_for("despesa"))

    return render_template("despesa.html")


@app.route("/estoque")
@role_required(*ESTOQUE_ROLES)
def estoque():
    return render_template("estoque.html", estoque=Produto.query.order_by(Produto.nome).all())


@app.route("/estoque/remover/<int:id>", methods=["POST"])
@role_required(*ESTOQUE_ROLES)
def remover_produto(id):
    if not exigir_caixa_aberto():
        return redirect(url_for("estoque"))

    produto = db.session.get(Produto, id)
    if not produto:
        flash("Produto não encontrado.")
        return redirect(url_for("estoque"))

    # Se o produto já participou de alguma venda/histórico, ele não pode ser
    # apagado do banco, pois os itens da venda precisam continuar preservados.
    # Nesse caso, a ação "remover" apenas zera o estoque atual do produto.
    vendas_com_produto = ItemVenda.query.filter_by(produto_id=produto.id).first()

    try:
        if vendas_com_produto:
            produto.quantidade = Decimal("0")
            db.session.commit()
            flash("O produto já possui operações no histórico. O estoque foi zerado e o histórico foi preservado.")
        else:
            if produto.imagem:
                arquivo_imagem = UPLOAD_DIR / produto.imagem
                if arquivo_imagem.exists():
                    arquivo_imagem.unlink()
            db.session.delete(produto)
            db.session.commit()
            flash("Produto removido do estoque e do banco de dados.")
    except Exception:
        db.session.rollback()
        flash("Não foi possível remover o produto.")

    return redirect(url_for("estoque"))


@app.route("/historico")
@role_required("root", "gerente", "gestor_caixa", "gestor_estoque")
def historico():
    vendas = Venda.query.order_by(Venda.data.desc()).all()
    despesas = Despesa.query.order_by(Despesa.data.desc()).all()
    produtos_vendidos = {}
    for venda in vendas:
        for item in venda.itens:
            nome = item.produto.nome
            produtos_vendidos[nome] = produtos_vendidos.get(nome, 0) + float(item.quantidade)
    produtos_vendidos = dict(sorted(produtos_vendidos.items(), key=lambda x: (-x[1], x[0].lower())))
    return render_template("historico.html", vendas=vendas, despesas=despesas, produtos_vendidos=produtos_vendidos)


@app.route("/ranking-caixa")
@role_required(*RANKING_ROLES)
def ranking_caixa():
    """Ranking de faturamento dos Gestores de Caixa.

    O faturamento é atribuído ao usuário que abriu a sessão do caixa.
    Sessões abertas por Root, Gerente ou Gestor de Estoque nunca entram no ranking.
    """
    agregados = {}
    caixas_qualificados = Caixa.query.filter_by(cargo_abertura="gestor_caixa").all()

    for caixa in caixas_qualificados:
        usuario = caixa.usuario_abertura
        if not usuario:
            continue

        dados = agregados.setdefault(
            usuario.id,
            {
                "usuario": usuario,
                "faturamento": Decimal("0"),
                "vendas": 0,
                "caixas": 0,
            },
        )
        dados["caixas"] += 1
        vendas_caixa = Venda.query.filter_by(caixa_id=caixa.id).all()
        dados["vendas"] += len(vendas_caixa)
        dados["faturamento"] += sum(
            (Decimal(str(v.valor_total)) for v in vendas_caixa),
            Decimal("0"),
        )

    ranking = sorted(
        agregados.values(),
        key=lambda item: (-item["faturamento"], -item["vendas"], item["usuario"].nome.lower()),
    )

    for posicao, item in enumerate(ranking, start=1):
        item["posicao"] = posicao

    return render_template("ranking_caixa.html", ranking=ranking)


@app.route("/historico-caixa")
@role_required(*HISTORICO_CAIXA_ROLES)
def historico_caixa():
    caixas = Caixa.query.order_by(Caixa.aberto_em.desc()).all()
    dados = []
    for caixa in caixas:
        entradas = sum((m.valor for m in caixa.movimentacoes if m.tipo == "entrada"), Decimal("0"))
        saidas = sum((m.valor for m in caixa.movimentacoes if m.tipo == "saida"), Decimal("0"))
        dados.append({"caixa": caixa, "entradas": entradas, "saidas": saidas, "saldo": entradas - saidas})
    return render_template("historico_caixa.html", caixas=dados)


@app.route("/caixa")
@caixa_required()
def caixa():
    caixa_obj = caixa_atual()
    movimentacoes = MovimentacaoCaixa.query.order_by(MovimentacaoCaixa.data.desc()).all()
    totais = totais_caixa_total()

    sessao_totais = {"entrada": Decimal("0"), "saida": Decimal("0"), "saldo": Decimal("0")}
    if caixa_obj:
        for movimentacao in caixa_obj.movimentacoes:
            sessao_totais[movimentacao.tipo] = sessao_totais.get(movimentacao.tipo, Decimal("0")) + movimentacao.valor
        sessao_totais["saldo"] = sessao_totais["entrada"] - sessao_totais["saida"]

    return render_template(
        "caixa.html",
        caixa_obj=caixa_obj,
        movimentacoes=movimentacoes,
        totais=totais,
        sessao_totais=sessao_totais,
    )


@app.route("/caixa/abrir", methods=["POST"])
@caixa_required()
def abrir_caixa():
    usuario = usuario_atual()
    caixa_obj, criou = abrir_caixa_interno(usuario)
    if criou:
        flash(f"Caixa aberto por {usuario.nome}.")
    else:
        flash(f"O caixa já está aberto por {caixa_obj.usuario_abertura.nome if caixa_obj.usuario_abertura else 'usuário não identificado'}.")
    return redirect(url_for("caixa"))


@app.route("/caixa/fechar", methods=["POST"])
@caixa_required()
def fechar_caixa():
    usuario = usuario_atual()
    caixa_obj = fechar_caixa_interno(usuario)
    if caixa_obj:
        flash(f"Caixa fechado por {usuario.nome}.")
    else:
        flash("Não há caixa aberto para fechar.")
    return redirect(url_for("caixa"))


@app.route("/usuarios", methods=["GET", "POST"])
@role_required(*USUARIO_ROLES)
def usuarios_admin():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        usuario_nome = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "")
        cargo = request.form.get("cargo", "gestor_estoque").strip().lower()
        arquivo = request.files.get("imagem")
        imagem = None

        if arquivo and arquivo.filename:
            if not allowed_image(arquivo.filename):
                flash("Formato de imagem inválido. Use PNG, JPG, JPEG, GIF ou WEBP.")
                return redirect(url_for("usuarios_admin"))
            nome_seguro = secure_filename(arquivo.filename)
            if not nome_seguro:
                flash("Nome de imagem inválido.")
                return redirect(url_for("usuarios_admin"))
            nome_final = f"usuario_{uuid4().hex}_{nome_seguro}"
            arquivo.save(UPLOAD_DIR / nome_final)
            imagem = nome_final

        if cargo not in {"gerente", "gestor_caixa", "gestor_estoque"}:
            flash("O cargo selecionado é inválido. O Root não pode ser criado por esta tela.")
        elif not nome or not usuario_nome or not senha:
            flash("Nome, usuário e senha são obrigatórios.")
        elif Usuario.query.filter_by(usuario=usuario_nome).first():
            flash("Esse usuário já existe.")
        else:
            db.session.add(
                Usuario(
                    nome=nome,
                    usuario=usuario_nome,
                    senha_hash=hash_password(senha),
                    imagem=imagem,
                    cargo=cargo,
                )
            )
            db.session.commit()
            flash(f"Usuário adicionado como {ROLE_LABELS[cargo]}!")
        return redirect(url_for("usuarios_admin"))

    return render_template("usuarios.html", usuarios=Usuario.query.order_by(Usuario.usuario).all())


@app.route("/usuarios/editar/<int:id>", methods=["GET", "POST"])
@role_required(*USUARIO_ROLES)
def editar_usuario(id):
    usuario = db.session.get(Usuario, id)
    atual = usuario_atual()

    if not usuario:
        flash("Usuário não encontrado.")
        return redirect(url_for("usuarios_admin"))

    # O Root só pode ser editado pelo próprio Root e nunca perde o cargo Root.
    if usuario.cargo == "root" and (not atual or atual.id != usuario.id or atual.cargo != "root"):
        flash("Somente o próprio Root pode editar seus dados.")
        return redirect(url_for("usuarios_admin"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        usuario_nome = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "")
        cargo = usuario.cargo if usuario.cargo == "root" else request.form.get("cargo", "gestor_estoque").strip().lower()
        arquivo = request.files.get("imagem")

        if not nome or not usuario_nome:
            flash("Nome e usuário são obrigatórios.")
            return redirect(url_for("editar_usuario", id=id))

        if cargo not in {"root", "gerente", "gestor_caixa", "gestor_estoque"}:
            flash("Cargo inválido.")
            return redirect(url_for("editar_usuario", id=id))

        outro = Usuario.query.filter(Usuario.usuario == usuario_nome, Usuario.id != usuario.id).first()
        if outro:
            flash("Esse nome de usuário já está em uso.")
            return redirect(url_for("editar_usuario", id=id))

        if cargo == "root":
            outro_root = Usuario.query.filter(Usuario.cargo == "root", Usuario.id != usuario.id).first()
            if outro_root:
                flash("Já existe outro Root. O sistema permite apenas um Root.")
                return redirect(url_for("editar_usuario", id=id))

        if arquivo and arquivo.filename:
            if not allowed_image(arquivo.filename):
                flash("Formato de imagem inválido. Use PNG, JPG, JPEG, GIF ou WEBP.")
                return redirect(url_for("editar_usuario", id=id))
            nome_seguro = secure_filename(arquivo.filename)
            if not nome_seguro:
                flash("Nome de imagem inválido.")
                return redirect(url_for("editar_usuario", id=id))
            nome_final = f"usuario_{uuid4().hex}_{nome_seguro}"
            arquivo.save(UPLOAD_DIR / nome_final)

            if usuario.imagem:
                imagem_anterior = UPLOAD_DIR / usuario.imagem
                if imagem_anterior.exists():
                    try:
                        imagem_anterior.unlink()
                    except OSError:
                        pass
            usuario.imagem = nome_final

        usuario.nome = nome
        usuario.usuario = usuario_nome
        usuario.cargo = cargo
        if senha.strip():
            usuario.senha_hash = hash_password(senha)

        try:
            db.session.commit()
            if atual and atual.id == usuario.id:
                session["usuario"] = usuario.usuario
            flash("Usuário atualizado com sucesso!")
            return redirect(url_for("usuarios_admin"))
        except Exception:
            db.session.rollback()
            flash("Não foi possível atualizar o usuário.")
            return redirect(url_for("editar_usuario", id=id))

    return render_template("editar_usuario.html", usuario=usuario, roles_labels=ROLE_LABELS)


@app.route("/usuarios/remover/<int:id>", methods=["POST"])
@role_required(*USUARIO_ROLES)
def remover_usuario(id):
    usuario = db.session.get(Usuario, id)
    atual = usuario_atual()
    if not usuario:
        flash("Usuário não encontrado.")
        return redirect(url_for("usuarios_admin"))

    if usuario.cargo == "root":
        flash("O Root não pode ser removido individualmente. Use 'Excluir loja' pelo próprio Root.")
        return redirect(url_for("usuarios_admin"))

    if usuario.id == atual.id:
        flash("Você não pode remover o próprio usuário por esta tela.")
        return redirect(url_for("usuarios_admin"))

    try:
        db.session.delete(usuario)
        db.session.commit()
        flash("Usuário removido!")
    except Exception:
        db.session.rollback()
        flash("Não foi possível remover o usuário.")

    return redirect(url_for("usuarios_admin"))


@app.route("/loja/excluir", methods=["POST"])
@role_required("root")
def excluir_loja():
    try:
        apagar_loja()
        session.clear()
        flash("Todos os dados da loja foram apagados. Cadastre um novo Root para começar novamente.")
        return redirect(url_for("configurar_root"))
    except Exception:
        flash("Não foi possível apagar a loja.")
        return redirect(url_for("usuarios_admin"))


if __name__ == "__main__":
    app.run(debug=True)
