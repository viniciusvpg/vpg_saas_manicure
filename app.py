from flask import Flask, redirect, render_template, request, url_for, session, flash, jsonify
from models import db, Estabelecimento, Servico, Agendamento, Cliente, Pacote, ClientePacote, ConfigHorario
from datetime import datetime
from functools import wraps
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Configuração do banco SQLite
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///saas_agenda.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'chave_secreta_para_sessoes'

db.init_app(app)
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Cria as tabelas automaticamente se não existirem
with app.app_context():
    db.create_all()

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('is_super_admin') != True:
            return redirect(url_for('login_master'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def dashboard():
    if 'estabelecimento_id' not in session: 
        return redirect(url_for('login'))
        
    estabelecimento_id_logado = session['estabelecimento_id']
    
    hoje = datetime.now()
    inicio_dia = hoje.replace(hour=0, minute=0, second=0)
    fim_dia = hoje.replace(hour=23, minute=59, second=59)

    agendamentos_hoje = Agendamento.query.filter(
        Agendamento.estabelecimento_id == estabelecimento_id_logado,
        Agendamento.data_hora >= inicio_dia,
        Agendamento.data_hora <= fim_dia
    ).order_by(Agendamento.data_hora.asc()).all()

    total_atendimentos = len([a for a in agendamentos_hoje if a.status != 'Não Compareceu'])
    faturamento_est = sum(a.servico.valor for a in agendamentos_hoje if a.status != 'Não Compareceu')

    proximo_id = None
    for a in agendamentos_hoje:
        if a.data_hora > hoje and a.status == 'Confirmado':
            proximo_id = a.id
            break 

    agenda_hoje = []
    for a in agendamentos_hoje:
        agenda_hoje.append({
            "id": a.id,                                 
            "tipo_pagamento": a.tipo_pagamento,         
            "hora": a.data_hora.strftime('%H:%M'),
            "nome": a.cliente.nome,
            "servico": a.servico.nome_servico,
            "telefone": a.cliente.whatsapp,
            "status": a.status,
            "is_proximo": (a.id == proximo_id)
        })

    dados_dinamicos = {
        "nome_estabelecimento": session['estabelecimento_nome'], 
        "agendamentos_hoje": total_atendimentos,
        "novos_bot": len([a for a in agendamentos_hoje if a.status == 'Confirmado']),
        "faturamento_est": faturamento_est,
        "agenda_hoje": agenda_hoje
    }
    
    return render_template('dashboard.html', dados=dados_dinamicos)

@app.route('/agenda/concluir/<int:id>', methods=['POST'])
def concluir_agendamento(id):
    if 'estabelecimento_id' not in session: return redirect(url_for('login'))
    
    agendamento = Agendamento.query.get_or_404(id)
    agendamento.status = 'Concluído'
    agendamento.pago = True 
    db.session.commit()
    
    return redirect(url_for('agenda', data=agendamento.data_hora.strftime('%Y-%m-%d')))

@app.route('/agenda/cancelar/<int:id>', methods=['POST'])
def cancelar_agendamento(id):
    if 'estabelecimento_id' not in session: return redirect(url_for('login'))
    
    agendamento = Agendamento.query.get_or_404(id)
    agendamento.status = 'Não Compareceu'
    
    if agendamento.tipo_pagamento == 'Pacote':
        pacote_cliente = ClientePacote.query.filter_by(
            cliente_id=agendamento.cliente_id
        ).order_by(ClientePacote.data_compra.desc()).first()
        
        if pacote_cliente:
            pacote_cliente.sessoes_restantes += 1
            pacote_cliente.ativo = True
            db.session.add(pacote_cliente)
            
    db.session.commit()
    return redirect(url_for('agenda', data=agendamento.data_hora.strftime('%Y-%m-%d')))

@app.route('/financeiro')
def financeiro():
    if 'estabelecimento_id' not in session: return redirect(url_for('login'))
    estabelecimento_id_logado = session['estabelecimento_id']
    
    vendas_pacotes = ClientePacote.query.join(Pacote).filter(Pacote.estabelecimento_id == estabelecimento_id_logado).order_by(ClientePacote.data_compra.desc()).all()
    total_pacotes = sum(vp.pacote_comprado.valor_total for vp in vendas_pacotes)
    
    avulsos_pagos = Agendamento.query.filter_by(
        estabelecimento_id=estabelecimento_id_logado, 
        tipo_pagamento='Avulso', 
        pago=True, 
        status='Concluído'
    ).order_by(Agendamento.data_hora.desc()).all()
    total_avulso = sum(ap.servico.valor for ap in avulsos_pagos)
    
    return render_template(
        'financeiro.html',
        vendas_pacotes=vendas_pacotes,
        avulsos_pagos=avulsos_pagos,
        total_pacotes=total_pacotes,
        total_avulso=total_avulso,
        total_geral=total_pacotes + total_avulso
    )

@app.route('/servicos', methods=['GET', 'POST'])
def servicos():
    if 'estabelecimento_id' not in session: return redirect(url_for('login'))
    estabelecimento_id_logado = session['estabelecimento_id']
    
    if request.method == 'POST':
        nome = request.form.get('nome_servico')
        valor = float(request.form.get('valor').replace(',', '.'))
        duracao = int(request.form.get('duracao_minutos'))
        
        novo_servico = Servico(
            estabelecimento_id=estabelecimento_id_logado,
            nome_servico=nome,
            valor=valor,
            duracao_minutos=duracao
        )
        db.session.add(novo_servico)
        db.session.commit()
        return redirect(url_for('servicos'))
        
    lista_servicos = Servico.query.filter_by(estabelecimento_id=estabelecimento_id_logado).all()
    return render_template('servicos.html', servicos=lista_servicos)

@app.route('/agenda', methods=['GET', 'POST'])
def agenda():
    if 'estabelecimento_id' not in session: return redirect(url_for('login'))
    estabelecimento_id_logado = session['estabelecimento_id']
    
    if request.method == 'POST':
        cliente_id = request.form.get('cliente_id')
        servico_id = request.form.get('servico_id')
        data_hora_str = request.form.get('data_hora')
        
        novo_agendamento = Agendamento(
            estabelecimento_id=estabelecimento_id_logado,
            cliente_id=cliente_id,
            servico_id=servico_id,
            data_hora=datetime.strptime(data_hora_str, '%Y-%m-%dT%H:%M'),
            status="Confirmado"
        )
        db.session.add(novo_agendamento)
        db.session.commit()
        data_foco = data_hora_str.split('T')[0]
        return redirect(url_for('agenda', data=data_foco))

    data_url = request.args.get('data', datetime.now().strftime('%Y-%m-%d'))
    data_objeto = datetime.strptime(data_url, '%Y-%m-%d')
    inicio_dia = data_objeto.replace(hour=0, minute=0, second=0)
    fim_dia = data_objeto.replace(hour=23, minute=59, second=59)
    
    agendamentos_dia = Agendamento.query.filter(
        Agendamento.estabelecimento_id == estabelecimento_id_logado,
        Agendamento.data_hora >= inicio_dia,
        Agendamento.data_hora <= fim_dia
    ).order_by(Agendamento.data_hora.asc()).all()
    
    lista_servicos = Servico.query.filter_by(estabelecimento_id=estabelecimento_id_logado).all()
    lista_clientes = Cliente.query.filter_by(estabelecimento_id=estabelecimento_id_logado).all()
    
    return render_template(
        'agenda.html', 
        agendamentos=agendamentos_dia, 
        data_selecionada=data_url,
        servicos=lista_servicos,
        clientes=lista_clientes
    )

@app.route('/pacotes', methods=['GET', 'POST'])
def pacotes():
    if 'estabelecimento_id' not in session: return redirect(url_for('login'))
    estabelecimento_id_logado = session['estabelecimento_id']
    
    if request.method == 'POST':
        nome = request.form.get('nome_pacote')
        valor = float(request.form.get('valor_total').replace(',', '.'))
        qtd = int(request.form.get('qtd_sessoes'))
        
        novo_pacote = Pacote(
            estabelecimento_id=estabelecimento_id_logado,
            nome_pacote=nome,
            valor_total=valor,
            qtd_sessoes=qtd
        )
        db.session.add(novo_pacote)
        db.session.commit()
        return redirect(url_for('pacotes'))
        
    lista_pacotes = Pacote.query.filter_by(estabelecimento_id=estabelecimento_id_logado).order_by(Pacote.nome_pacote.asc()).all()
    return render_template('pacotes.html', pacotes=lista_pacotes)

@app.route('/clientes', methods=['GET', 'POST'])
def clientes():
    if 'estabelecimento_id' not in session: return redirect(url_for('login'))
    estabelecimento_id_logado = session['estabelecimento_id']
    
    if request.method == 'POST':
        nome = request.form.get('nome')
        whatsapp = request.form.get('whatsapp') 
        
        nova_cliente = Cliente(estabelecimento_id=estabelecimento_id_logado, nome=nome, whatsapp=whatsapp)
        db.session.add(nova_cliente)
        db.session.commit()
        return redirect(url_for('clientes'))
        
    lista_clientes = Cliente.query.filter_by(estabelecimento_id=estabelecimento_id_logado).order_by(Cliente.nome.asc()).all()
    lista_pacotes = Pacote.query.filter_by(estabelecimento_id=estabelecimento_id_logado).order_by(Pacote.nome_pacote.asc()).all()
    
    return render_template('clientes.html', clientes=lista_clientes, pacotes=lista_pacotes)

@app.route('/vender_pacote', methods=['POST'])
def vender_pacote():
    if 'estabelecimento_id' not in session: return redirect(url_for('login'))
    
    cliente_id = request.form.get('cliente_id')
    pacote_id = request.form.get('pacote_id')
    pacote = Pacote.query.get(pacote_id)
    
    if pacote:
        nova_venda = ClientePacote(
            cliente_id=cliente_id,
            pacote_id=pacote_id,
            sessoes_restantes=pacote.qtd_sessoes,
            ativo=True
        )
        db.session.add(nova_venda)
        db.session.commit()
        
    return redirect(url_for('clientes'))

@app.route('/horarios', methods=['GET', 'POST'])
def horarios():
    if 'estabelecimento_id' not in session: return redirect(url_for('login'))
    estabelecimento_id_logado = session['estabelecimento_id']
    dias_semana = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado', 'Domingo']

    if request.method == 'POST':
        for i in range(7):
            ativo = request.form.get(f'ativo_{i}') == 'on'
            hora_inicio = request.form.get(f'hora_inicio_{i}')
            hora_fim = request.form.get(f'hora_fim_{i}')
            almoco_inicio = request.form.get(f'almoco_inicio_{i}')
            almoco_fim = request.form.get(f'almoco_fim_{i}')

            config = ConfigHorario.query.filter_by(estabelecimento_id=estabelecimento_id_logado, dia_semana=i).first()
            if not config:
                config = ConfigHorario(estabelecimento_id=estabelecimento_id_logado, dia_semana=i)
                db.session.add(config)
            
            config.ativo = ativo
            config.hora_inicio = hora_inicio if hora_inicio else "08:00"
            config.hora_fim = hora_fim if hora_fim else "18:00"
            config.almoco_inicio = almoco_inicio if almoco_inicio else None
            config.almoco_fim = almoco_fim if almoco_fim else None

        db.session.commit()
        return redirect(url_for('horarios'))

    configs = ConfigHorario.query.filter_by(estabelecimento_id=estabelecimento_id_logado).all()
    mapa_configs = {c.dia_semana: c for c in configs}
    return render_template('horarios.html', dias_semana=dias_semana, mapa_configs=mapa_configs)

@app.route('/upload_logo', methods=['POST'])
def upload_logo():
    if 'estabelecimento_id' not in session: return redirect(url_for('login'))
    
    if 'logo_file' not in request.files:
        return redirect(request.referrer)
        
    file = request.files['logo_file']
    if file.filename == '':
        return redirect(request.referrer)
        
    if file:
        # Cria um nome seguro e único para a imagem
        extensao = file.filename.rsplit('.', 1)[1].lower()
        nome_arquivo = f"logo_cliente_{session['estabelecimento_id']}.{extensao}"
        caminho_completo = os.path.join(app.config['UPLOAD_FOLDER'], nome_arquivo)
        
        # Salva o arquivo na pasta
        file.save(caminho_completo)
        
        # Salva no banco de dados e atualiza a sessão
        estabelecimento = Estabelecimento.query.get(session['estabelecimento_id'])
        estabelecimento.logo = nome_arquivo
        db.session.commit()
        session['logo'] = nome_arquivo
        
        flash("Logo atualizada com sucesso!")
        
    return redirect(request.referrer)

@app.route('/atualizar_tema', methods=['POST'])
def atualizar_tema():
    if 'estabelecimento_id' not in session: 
        return redirect(url_for('login'))
        
    novo_tema = request.form.get('tema')
    
    # Valida se o tema escolhido é um dos permitidos
    if novo_tema in ['manicure', 'barbearia', 'tatuagem']:
        estabelecimento = Estabelecimento.query.get(session['estabelecimento_id'])
        estabelecimento.nicho = novo_tema
        db.session.commit()
        
        # Atualiza a memória da sessão atual
        session['nicho'] = novo_tema
        flash("Tema visual atualizado!")
        
    return redirect(request.referrer)

@app.route('/toggle_estabelecimento/<int:id>', methods=['POST'])
@admin_required
def toggle_estabelecimento(id):
    estabelecimento = Estabelecimento.query.get_or_404(id)
    estabelecimento.ativo = not estabelecimento.ativo
    db.session.commit()
    status_str = "ativada" if estabelecimento.ativo else "suspensa/desativada"
    flash(f'A conta de {estabelecimento.nome} foi {status_str} com sucesso!')
    return redirect(url_for('painel_master'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        telefone = request.form.get('telefone')
        senha = request.form.get('senha')
        
        estabelecimento = Estabelecimento.query.filter_by(telefone_bot=telefone, senha=senha).first()
        
        if estabelecimento:
            if not estabelecimento.ativo:
                flash('Seu acesso está suspenso. Entre em contato com o administrador do sistema.')
                return render_template('login.html')
                
            session['estabelecimento_id'] = estabelecimento.id
            session['estabelecimento_nome'] = estabelecimento.nome
            session['nicho'] = estabelecimento.nicho # <- INJEÇÃO DO TEMA
            session['logo'] = estabelecimento.logo
            return redirect(url_for('dashboard'))
            
        flash('Usuário ou senha incorretos.')
    return render_template('login.html')

@app.route('/meu_bot')
def meu_bot():
    if 'estabelecimento_id' not in session: return redirect(url_for('login'))
    dados_dinamicos = {
        "nome_estabelecimento": session.get('estabelecimento_nome')
    }
    return render_template('meu_bot.html', dados=dados_dinamicos)

@app.route('/api/bot/check-cliente', methods=['POST'])
def bot_check_cliente():
    dados = request.json
    manicure_id = dados.get('estabelecimento_id')
    whatsapp = dados.get('whatsapp')

    # Verifica se o cliente já existe no banco de dados
    cliente = Cliente.query.filter_by(manicure_id=manicure_id, whatsapp=whatsapp).first()[cite: 4]
    if cliente:
        return jsonify({"registrado": True, "nome": cliente.nome})
    
    return jsonify({"registrado": False})

@app.route('/api/bot/servicos', methods=['GET'])
def get_bot_servicos():
    estabelecimento_id = request.args.get('estabelecimento_id')
    if not estabelecimento_id:
        return jsonify({"erro": "estabelecimento_id nao informado"}), 400
        
    servicos = Servico.query.filter_by(estabelecimento_id=estabelecimento_id).all()[cite: 5, 6]
    
    lista_servicos = []
    for s in servicos:
        lista_servicos.append({
            "id": s.id,
            "nome": s.nome_servico,
            "valor": s.valor,
            "duracao": s.duracao_minutos
        })[cite: 6]
        
    return jsonify({"servicos": lista_servicos})

@app.route('/api/bot/registrar-agendamento', methods=['POST'])
def bot_registrar_agendamento():
    dados = request.json
    manicure_id = dados.get('estabelecimento_id')
    whatsapp = dados.get('whatsapp')
    nome = dados.get('nome')
    servico_nome = dados.get('servico')
    
    # O robô envia "Sex 25/05". Vamos quebrar para pegar o dia e o mês.
    data_str = dados.get('data') 
    hora_str = dados.get('hora') 

    # 1. Cadastra ou recupera a Cliente
    cliente = Cliente.query.filter_by(manicure_id=manicure_id, whatsapp=whatsapp).first()[cite: 4]
    if not cliente:
        cliente = Cliente(manicure_id=manicure_id, nome=nome, whatsapp=whatsapp)[cite: 4]
        db.session.add(cliente)
        db.session.flush() # Salva temporariamente para gerar o ID do cliente

    # 2. Identifica o ID do Serviço (se houver)
    servico = Servico.query.filter_by(manicure_id=manicure_id, nome_servico=servico_nome).first() if servico_nome else None[cite: 4]
    servico_id = servico.id if servico else None

    # 3. Formata a Data e Hora para o SQLAlchemy salvar corretamente
    try:
        # Ex: Pega "25" e "05" de "Sex 25/05"
        dia, mes = map(int, data_str.split(' ')[1].split('/'))
        ano = datetime.now().year
        hora, minuto = map(int, hora_str.split(':'))
        data_hora_final = datetime(ano, mes, dia, hora, minuto)
    except:
        # Em caso de erro na conversão da string, usa a data atual como fallback
        data_hora_final = datetime.now()

    # 4. Salva o Agendamento no Painel
    novo_agendamento = Agendamento(
        manicure_id=manicure_id,
        cliente_id=cliente.id,
        servico_id=servico_id,
        data_hora=data_hora_final,
        status="Agendado",
        tipo_pagamento="Avulso",
        pago=False
    )
    db.session.add(novo_agendamento)
    db.session.commit()

    return jsonify({"status": "sucesso"})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/mestre_do_saas', methods=['GET', 'POST'])
def login_master():
    if request.method == 'POST':
        senha = request.form.get('senha_master')
        if senha == 'Vpg@1462': 
            session['is_super_admin'] = True
            return redirect(url_for('painel_master'))
        flash('Chave Mestra Incorreta.')
    return render_template('login_master.html')

@app.route('/painel_master', methods=['GET', 'POST'])
@admin_required
def painel_master():
    if request.method == 'POST':
        nome = request.form.get('nome')
        telefone = request.form.get('telefone')
        senha = request.form.get('senha')
        nicho = request.form.get('nicho', 'manicure') # Captura o nicho selecionado
        
        nova = Estabelecimento(nome=nome, telefone_bot=telefone, senha=senha, nicho=nicho)
        db.session.add(nova)
        db.session.commit()
        
        for d in range(5):
            h = ConfigHorario(estabelecimento_id=nova.id, dia_semana=d, hora_inicio="08:00", hora_fim="18:00")
            db.session.add(h)
        db.session.commit()
        
        flash(f'Conta de {nome} criada com sucesso!')
        return redirect(url_for('painel_master'))

    todas = Estabelecimento.query.all()
    return render_template('painel_master.html', estabelecimentos=todas)

@app.route('/mudar_senha_estabelecimento/<int:id>', methods=['POST'])
@admin_required
def mudar_senha_estabelecimento(id):
    estabelecimento = Estabelecimento.query.get_or_404(id)
    nova_senha = request.form.get('nova_senha')
    
    if nova_senha:
        estabelecimento.senha = nova_senha
        db.session.commit()
        flash(f'Senha da cliente {estabelecimento.nome} alterada com sucesso!')
        
    return redirect(url_for('painel_master'))

@app.route('/logout_master')
def logout_master():
    session['is_super_admin'] = False
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)