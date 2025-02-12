from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import json
from sqlalchemy.types import JSON
from sqlalchemy.ext.mutable import MutableDict, MutableList
from datetime import datetime, timedelta
import secrets

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chave-secreta'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///utilizadores.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Por favor, inicie sessão para aceder a esta página.'

# Modelo do Utilizador
class Address(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    nome = db.Column(db.String(100))
    rua = db.Column(db.String(200))
    numero = db.Column(db.String(20))
    codigo_postal = db.Column(db.String(20))
    cidade = db.Column(db.String(100))
    distrito = db.Column(db.String(100))
    telefone = db.Column(db.String(20))
    padrao = db.Column(db.Boolean, default=False)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(80), nullable=False)  # Nome completo do utilizador
    username = db.Column(db.String(80), unique=True, nullable=False)  # Nome de utilizador para login
    email = db.Column(db.String(120), unique=True, nullable=False)  # Email do utilizador
    password_hash = db.Column(db.String(128))
    reset_token = db.Column(db.String(100), unique=True)
    reset_token_expiry = db.Column(db.DateTime)
    carrinho = db.Column(MutableDict.as_mutable(JSON), default=lambda: {"items": [], "total": 0})
    favoritos = db.Column(MutableList.as_mutable(JSON), default=list)
    enderecos = db.relationship('Address', backref='user', lazy=True)

    def __init__(self, nome, username, email):
        self.nome = nome
        self.username = username
        self.email = email
        self.carrinho = {"items": [], "total": 0}
        self.favoritos = []

    def set_password(self, password):        
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):        
        return check_password_hash(self.password_hash, password)

    def generate_reset_token(self):        
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expiry = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()
        return self.reset_token

    def verify_reset_token(self, token):        
        if (self.reset_token != token or 
            self.reset_token_expiry is None or 
            datetime.utcnow() > self.reset_token_expiry):
            return False
        return True

    def adicionar_ao_carrinho(self, produto):        
        if not isinstance(self.carrinho, dict):
            self.carrinho = {"items": [], "total": 0}
        
        # Verifica se o produto já existe no carrinho
        for item in self.carrinho["items"]:
            if item["id"] == produto["id"]:
                item["quantidade"] += 1
                item["subtotal"] = item["quantidade"] * item["preco"]
                break
        else:
            # Adiciona novo item se não existir
            self.carrinho["items"].append({
                "id": produto["id"],
                "titulo": produto["title"],
                "preco": produto["price"],
                "imagem": produto["image"],
                "quantidade": 1,
                "subtotal": produto["price"]
            })
        
        # Atualiza o total
        self.carrinho["total"] = sum(item["subtotal"] for item in self.carrinho["items"])
        db.session.commit()

    def remover_do_carrinho(self, produto_id):        
        if not isinstance(self.carrinho, dict):
            return
        
        self.carrinho["items"] = [item for item in self.carrinho["items"] if item["id"] != produto_id]
        self.carrinho["total"] = sum(item["subtotal"] for item in self.carrinho["items"])
        db.session.commit()

    def atualizar_quantidade(self, produto_id, quantidade):        
        if not isinstance(self.carrinho, dict):
            self.carrinho = {"items": [], "total": 0}
    
        print(f"Carrinho antes: {self.carrinho}")  # Debug
    
        # Garantir que produto_id é inteiro
        produto_id = int(produto_id)
        quantidade = int(quantidade)
    
        encontrado = False
        for item in self.carrinho["items"]:
            if int(item["id"]) == produto_id:
                item["quantidade"] = quantidade
                item["subtotal"] = quantidade * item["preco"]
                encontrado = True
                break
    
        if encontrado:
            self.carrinho["total"] = sum(item["subtotal"] for item in self.carrinho["items"])
            db.session.commit()
            print(f"Carrinho após atualização: {self.carrinho}")  # Debug
            return True
    
        return False

    def adicionar_endereco(self, dados_endereco):        
        if len(self.enderecos) >= 3:
            return False, "Limite máximo de 3 endereços atingido"
        
        novo_endereco = Address(**dados_endereco, user_id=self.id)
        if not self.enderecos:  # Se for o primeiro endereço
            novo_endereco.padrao = True
            
        db.session.add(novo_endereco)
        db.session.commit()
        return True, "Endereço adicionado com sucesso"

    def definir_endereco_padrao(self, endereco_id):        
        for endereco in self.enderecos:
            endereco.padrao = (endereco.id == endereco_id)
        db.session.commit()

    def adicionar_favorito(self, produto_id):        
        if self.favoritos is None:
            self.favoritos = []
        if produto_id not in self.favoritos:
            self.favoritos.append(produto_id)
            db.session.commit()
    
    def remover_favorito(self, produto_id):        
        if self.favoritos is None:
            return
        if produto_id in self.favoritos:
            self.favoritos.remove(produto_id)
            db.session.commit()

    def is_favorito(self, produto_id):        
        return self.favoritos and produto_id in self.favoritos

class Pedido(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    endereco_id = db.Column(db.Integer, db.ForeignKey('address.id'), nullable=False)
    data_pedido = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='pendente')  # pendente, pago, enviado, entregue
    metodo_pagamento = db.Column(db.String(50))
    total = db.Column(db.Float)
    items = db.Column(MutableList.as_mutable(JSON), default=list)

    # Relacionamentos
    user = db.relationship('User', backref='pedidos')
    endereco = db.relationship('Address')

def simular_envio_email(destino, assunto, mensagem):    
    print("\n=== Email Simulado ===")
    print(f"Para: {destino}")
    print(f"Assunto: {assunto}")
    print(f"Mensagem:\n{mensagem}")
    print("====================\n")

@login_manager.user_loader
def load_user(id):    
    return User.query.get(int(id))

# Funções auxiliares para produtos
def carregar_produtos():    
    try:
        #response = requests.get('https://fakestoreapi.com/products')
        response = requests.get('https://fakestoreapiserver.reactbd.com/products')
        
        produtos = response.json()
        # Garantir que os IDs são inteiros
        for produto in produtos:
            produto['id'] = int(produto['_id'])
        # Guardar em cache
        with open('produtos.json', 'w') as f:
            json.dump(produtos, f)
        return produtos
    except requests.RequestException:
        try:
            with open('produtos.json', 'r') as f:
                produtos = json.load(f)
                # Garantir que os IDs são inteiros
                for produto in produtos:
                    produto['id'] = int(produto['id'])
                return produtos
        except FileNotFoundError:
            return []

def obter_produtos():   
    try:
        with open('produtos.json', 'r') as f:
            produtos = json.load(f)
            # Garantir que os IDs são inteiros
            for produto in produtos:
                produto['id'] = int(produto['id'])
            return produtos
    except FileNotFoundError:
        return carregar_produtos()

def obter_produto(id):    
    try:
        id = int(id)  # Converter para inteiro
        produtos = obter_produtos()
        for produto in produtos:
            if int(produto['id']) == id:  # Garantir que ambos são inteiros
                return produto
        print(f"Produto não encontrado. ID procurado: {id}")  # Debug
        return None
    except ValueError as e:
        print(f"Erro ao converter ID: {e}")  # Debug
        return None

# Rotas da aplicação
@app.route('/')
def home():    
    busca = request.args.get('busca', '')
    categoria = request.args.get('categoria', '')
    ordem = request.args.get('ordem', '')
    produtos = obter_produtos()
    # Filtrar por busca
    if busca:
        produtos = [p for p in produtos if busca.lower() in p['title'].lower()]
    
    # Filtrar por categoria
    if categoria:
        produtos = [p for p in produtos if p['category'] == categoria]
    
    # Ordenar
    if ordem == 'preco_asc':
        produtos.sort(key=lambda x: x['price'])
    elif ordem == 'preco_desc':
        produtos.sort(key=lambda x: x['price'], reverse=True)
    
    # Obter categorias únicas para o filtro
    categorias = sorted(set(p['category'] for p in obter_produtos()))
    
    return render_template('home.html', 
                         products=produtos, 
                         categorias=categorias,
                         busca=busca,
                         categoria_selecionada=categoria,
                         ordem=ordem)

@app.route('/produto/<int:id>')
def produto(id):    
    produto = obter_produto(id)
    if produto is None:
        flash('Produto não encontrado')
        return redirect(url_for('home'))
    return render_template('produto.html', produto=produto)

@app.route('/registar', methods=['GET', 'POST'])
def register():    
    if request.method == 'POST':
        nome = request.form['nome']
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        # Verifica se o utilizador já existe
        if User.query.filter_by(username=username).first():
            flash('Nome de utilizador já existe')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email já registado')
            return redirect(url_for('register'))
        
        # Cria novo utilizador
        utilizador = User(nome=nome, username=username, email=email)
        utilizador.set_password(password)
        db.session.add(utilizador)
        db.session.commit()
        
        flash('Registo efetuado com sucesso!')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():    
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        remember = 'remember' in request.form
        
        # Tenta encontrar por username ou email
        utilizador = User.query.filter(
            (User.username == username) | (User.email == username)
        ).first()
        
        if utilizador and utilizador.check_password(password):
            login_user(utilizador, remember=remember)
            next_page = request.args.get('next')
            flash('Login efetuado com sucesso!', 'success')
            return redirect(next_page if next_page else url_for('home'))
        
        flash('Nome de utilizador/email ou palavra-passe inválidos', 'danger')
    
    return render_template('login.html')

@app.route('/recuperar-palavra-passe', methods=['GET', 'POST'])
def recuperar_palavra_passe():    
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == 'POST':
        email = request.form['email']
        utilizador = User.query.filter_by(email=email).first()
        
        if utilizador:
            token = utilizador.generate_reset_token()
            reset_url = url_for('reset_palavra_passe', token=token, _external=True)
            
            assunto = "Recuperação de Palavra-passe - Loja Online"
            mensagem = f"""
            Olá {utilizador.nome},

            Foi solicitada a recuperação da palavra-passe para a sua conta.
            Para definir uma nova palavra-passe, clique na ligação abaixo:

            {reset_url}

            Se não foi você que solicitou a recuperação, ignore este email.
            Esta ligação expira dentro de 1 hora.

            Com os melhores cumprimentos,
            Equipa Loja Online
            """
            
            simular_envio_email(email, assunto, mensagem)
        
        flash('Se o email existir no sistema, receberá instruções para recuperar a sua palavra-passe.', 'info')
        return redirect(url_for('login'))
    
    return render_template('recuperar_palavra_passe.html')

@app.route('/reset-palavra-passe/<token>', methods=['GET', 'POST'])
def reset_palavra_passe(token):    
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    utilizador = User.query.filter_by(reset_token=token).first()
    if not utilizador or not utilizador.verify_reset_token(token):
        flash('A ligação de recuperação é inválida ou expirou.', 'danger')
        return redirect(url_for('recuperar_palavra_passe'))

    if request.method == 'POST':
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if password != confirm_password:
            flash('As palavras-passe não coincidem.', 'danger')
            return redirect(url_for('reset_palavra_passe', token=token))
        
        utilizador.set_password(password)
        utilizador.reset_token = None
        utilizador.reset_token_expiry = None
        db.session.commit()
        
        flash('A sua palavra-passe foi alterada com sucesso!', 'success')
        return redirect(url_for('login'))
    
    return render_template('reset_palavra_passe.html')

@app.route('/logout')
@login_required
def logout():    
    logout_user()
    flash('Sessão terminada com sucesso', 'success')
    return redirect(url_for('home'))

@app.route('/carrinho')
@login_required
def carrinho():    
    return render_template('carrinho.html')

# Rotas da API
@app.route('/api/carrinho', methods=['GET'])
@login_required
def obter_carrinho():   
    return jsonify(current_user.carrinho)

@app.route('/api/carrinho/adicionar', methods=['POST'])
@login_required
def adicionar_carrinho():    
    try:
        produto_id = request.json.get('produto_id')
        print(f"ID recebido: {produto_id}, tipo: {type(produto_id)}")  # Debug
        
        produto_id = int(produto_id)
        produto = obter_produto(produto_id)
        
        if produto:
            current_user.adicionar_ao_carrinho(produto)
            return jsonify({
                'success': True, 
                'carrinho': current_user.carrinho,
                'mensagem': 'Produto adicionado com sucesso'
            })
        
        print(f"Produto não encontrado para o ID: {produto_id}")  # Debug
        return jsonify({
            'success': False, 
            'error': f'Produto não encontrado (ID: {produto_id})'
        }), 404
        
    except Exception as e:
        print(f"Erro ao adicionar ao carrinho: {str(e)}")  # Debug
        return jsonify({
            'success': False, 
            'error': f'Erro ao processar pedido: {str(e)}'
        }), 500

@app.route('/api/carrinho/remover', methods=['POST'])
@login_required
def remover_carrinho():   
    produto_id = request.json.get('produto_id')
    current_user.remover_do_carrinho(produto_id)
    return jsonify({'success': True, 'carrinho': current_user.carrinho})

@app.route('/api/carrinho/atualizar', methods=['POST'])
@login_required
def atualizar_carrinho():    
    try:
        produto_id = int(request.json.get('produto_id'))
        quantidade = int(request.json.get('quantidade'))
        
        # Validar quantidade
        if quantidade < 1:
            quantidade = 1
        if quantidade > 99:
            quantidade = 99
            
        # Debug
        print(f"Atualizando carrinho: produto_id={produto_id}, quantidade={quantidade}")
        
        current_user.atualizar_quantidade(produto_id, quantidade)
        
        return jsonify({
            'success': True, 
            'carrinho': current_user.carrinho,
            'mensagem': 'Quantidade atualizada com sucesso'
        })
        
    except ValueError as e:
        print(f"Erro de valor: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Valores inválidos fornecidos'
        }), 400
        
    except Exception as e:
        print(f"Erro ao atualizar carrinho: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Erro ao atualizar quantidade'
        }), 500

# Rotas dos favoritos
@app.route('/api/favoritos/adicionar', methods=['POST'])
@login_required
def adicionar_favorito():    
    produto_id = request.json.get('produto_id')
    current_user.adicionar_favorito(produto_id)
    return jsonify({'success': True, 'favoritos': current_user.favoritos})

@app.route('/api/favoritos/remover', methods=['POST'])
@login_required
def remover_favorito():    
    produto_id = request.json.get('produto_id')
    current_user.remover_favorito(produto_id)
    return jsonify({'success': True, 'favoritos': current_user.favoritos})

@app.route('/favoritos')
@login_required
def favoritos():    
    produtos_favoritos = []
    for produto_id in current_user.favoritos or []:
        produto = obter_produto(produto_id)
        if produto:
            produtos_favoritos.append(produto)
    return render_template('favoritos.html', produtos=produtos_favoritos)

@app.route('/checkout')
@login_required
def checkout():    
    if not current_user.carrinho or not current_user.carrinho.get('items'):
        flash('O seu carrinho está vazio', 'warning')
        return redirect(url_for('carrinho'))
    return render_template('checkout.html')

@app.route('/api/endereco/adicionar', methods=['POST'])
@login_required
def adicionar_endereco():    
    print("Recebendo requisição para adicionar endereço")  # Debug
    dados = request.json
    print(f"Dados recebidos: {dados}")  # Debug
    
    try:
        novo_endereco = Address(
            user_id=current_user.id,
            nome=dados['nome'],
            rua=dados['rua'],
            numero=dados['numero'],
            codigo_postal=dados['codigo_postal'],
            cidade=dados['cidade'],
            distrito=dados['distrito'],
            telefone=dados['telefone']
        )
        
        if not Address.query.filter_by(user_id=current_user.id).first():
            novo_endereco.padrao = True
            
        db.session.add(novo_endereco)
        db.session.commit()
        print("Endereço adicionado com sucesso")  # Debug
        
        return jsonify({
            'success': True,
            'message': 'Endereço adicionado com sucesso'
        })
        
    except Exception as e:
        print(f"Erro ao adicionar endereço: {str(e)}")  # Debug
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

@app.route('/api/endereco/padrao', methods=['POST'])
@login_required
def definir_endereco_padrao():    
    try:
        endereco_id = int(request.json.get('endereco_id'))
        enderecos = Address.query.filter_by(user_id=current_user.id).all()
        
        for endereco in enderecos:
            endereco.padrao = (endereco.id == endereco_id)
        
        db.session.commit()
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

@app.route('/api/pedido/criar', methods=['POST'])
@login_required
def criar_pedido():    
    if not current_user.carrinho or not current_user.carrinho.get('items'):
        return jsonify({
            'success': False,
            'error': 'Carrinho vazio'
        }), 400
    
    endereco_id = request.json.get('endereco_id')
    metodo_pagamento = request.json.get('metodo_pagamento')
    
    if not endereco_id:
        return jsonify({
            'success': False,
            'error': 'Endereço de entrega não selecionado'
        }), 400
        
    if not metodo_pagamento:
        return jsonify({
            'success': False,
            'error': 'Método de pagamento não selecionado'
        }), 400
        
    try:
        # Criar novo pedido
        pedido = Pedido(
            user_id=current_user.id,
            endereco_id=endereco_id,
            metodo_pagamento=metodo_pagamento,
            total=current_user.carrinho['total'],
            items=current_user.carrinho['items']
        )
        db.session.add(pedido)
        
        # Simular processamento do pagamento
        if metodo_pagamento == 'mbway':
            # Aqui seria integração com API MB WAY
            pedido.status = 'pago'
        elif metodo_pagamento == 'multibanco':
            # Gerar referência multibanco
            pedido.status = 'pendente'
        elif metodo_pagamento == 'cartao':
            # Aqui seria integração com gateway de pagamento
            pedido.status = 'pago'
        
        # Limpar o carrinho
        current_user.carrinho = {"items": [], "total": 0}
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Pedido criado com sucesso',
            'pedido_id': pedido.id
        })
    except Exception as e:
        print(f"Erro ao criar pedido: {str(e)}")  # Debug
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/pedidos')
@login_required
def pedidos():    
    # Obtém os pedidos ordenados por data (mais recente primeiro)
    pedidos_user = Pedido.query.filter_by(user_id=current_user.id)\
                              .order_by(Pedido.data_pedido.desc())\
                              .all()
    return render_template('pedidos.html', pedidos=pedidos_user)

@app.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_profile':
            current_user.nome = request.form.get('nome')
            current_user.email = request.form.get('email')
            db.session.commit()
            flash('Perfil atualizado com sucesso!', 'success')
            
        elif action == 'change_password':
            senha_atual = request.form.get('senha_atual')
            nova_senha = request.form.get('nova_senha')
            confirmar_senha = request.form.get('confirmar_senha')
            
            if not current_user.check_password(senha_atual):
                flash('Senha atual incorreta', 'danger')
            elif nova_senha != confirmar_senha:
                flash('As novas senhas não coincidem', 'danger')
            else:
                current_user.set_password(nova_senha)
                db.session.commit()
                flash('Senha alterada com sucesso!', 'success')
        
        return redirect(url_for('perfil'))
    
    # Obtém os últimos 5 pedidos
    ultimos_pedidos = Pedido.query.filter_by(user_id=current_user.id)\
                                 .order_by(Pedido.data_pedido.desc())\
                                 .limit(5).all()
    
    return render_template('perfil.html', ultimos_pedidos=ultimos_pedidos)

@app.route('/endereco/novo', methods=['GET', 'POST'])
@login_required
def novo_endereco():    
    if len(current_user.enderecos) >= 3:
        flash('Limite máximo de 3 endereços atingido', 'warning')
        return redirect(url_for('perfil'))
        
    if request.method == 'POST':
        dados = {
            'nome': request.form.get('nome'),
            'rua': request.form.get('rua'),
            'numero': request.form.get('numero'),
            'codigo_postal': request.form.get('codigo_postal'),
            'cidade': request.form.get('cidade'),
            'distrito': request.form.get('distrito'),
            'telefone': request.form.get('telefone')
        }
        
        try:
            sucesso, mensagem = current_user.adicionar_endereco(dados)
            if sucesso:
                flash(mensagem, 'success')
                return redirect(url_for('perfil'))
            else:
                flash(mensagem, 'danger')
        except Exception as e:
            flash('Erro ao adicionar endereço', 'danger')
            
    return render_template('endereco_form.html')

@app.route('/termos')
def termos():
    return render_template('termos.html')

@app.route('/privacidade')
def privacidade():
    return render_template('privacidade.html')

@app.route('/faq')
def faq():
    return render_template('faq.html')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()

        # Criar utilizador admin se não existir
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                nome='Administrador',
                username='admin',
                email='admin@lojaonline.pt'
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print('Utilizador admin criado com sucesso')            
    app.run(debug=True)