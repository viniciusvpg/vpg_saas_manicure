from flask import Flask, redirect, render_template, request, url_for, session, flash
from models import db, Manicure, Servico, Agendamento, Cliente, Pacote, ClientePacote, ConfigHorario
from datetime import datetime
from functools import wraps

app = Flask(__name__)

# Configuração do banco SQLite
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///saas_agenda.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'chave_secreta_para_sessoes'

db.init_app(app)

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
    if 'manicure_id' not in session: 
        return redirect(url_for('login'))
        
    manicure_id_logada = session['manicure_id']
    
    hoje = datetime.now()
    inicio_dia = hoje.replace(hour=0, minute=0, second=0)
    fim_dia = hoje.replace(hour=23, minute=59, second=59)

    agendamentos_hoje = Agendamento.query.filter(
        Agendamento.manicure_id == manicure_id_logada,
        Agendamento.data_hora >= inicio_dia,
        Agendamento.data_hora <= fim_dia
    ).order_by(Agendamento.data_hora.asc()).all()

    total_atendimentos = len([a for a in agendamentos_hoje if a.status != 'Não Compareceu'])
    faturamento_est = sum(a.servico.valor for a in agendamentos_hoje if a.status != 'Não Compareceu')

    # CORREÇÃO: Procura por 'Confirmado' em vez de 'Agendado'
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
        "nome_manicure": session['manicure_nome'], 
        "agendamentos_hoje": total_atendimentos,
        # CORREÇÃO: Conta como novo se estiver 'Confirmado'
        "novos_bot": len([a for a in agendamentos_hoje if a.status == 'Confirmado']),
        "faturamento_est": faturamento_est,
        "agenda_hoje": agenda_hoje
    }
    
    return render_template('dashboard.html', dados=dados_dinamicos)

# ROTA PARA CONFIRMAR QUE A CLIENTE FOI ATENDIDA E PAGOU
@app.route('/agenda/concluir/<int:id>', methods=['POST'])
def concluir_agendamento(id):
    if 'manicure_id' not in session: return redirect(url_for('login'))
    
    agendamento = Agendamento.query.get_or_404(id)
    agendamento.status = 'Concluído'
    agendamento.pago = True # Valida o pagamento no local se for avulso
    db.session.commit()
    
    return redirect(url_for('agenda', data=agendamento.data_hora.strftime('%Y-%m-%d')))

# ROTA PARA CASO A CLIENTE NÃO COMPAREÇA (FALTA)
@app.route('/agenda/cancelar/<int:id>', methods=['POST'])
def cancelar_agendamento(id):
    if 'manicure_id' not in session: return redirect(url_for('login'))
    
    agendamento = Agendamento.query.get_or_404(id)
    agendamento.status = 'Não Compareceu'
    
    # SE FOR CLIENTE DE PLANO: Devolve 1 sessão ao saldo dela automaticamente
    if agendamento.tipo_pagamento == 'Pacote':
        pacote_cliente = ClientePacote.query.filter_by(
            cliente_id=agendamento.cliente_id
        ).order_by(ClientePacote.data_compra.desc()).first()
        
        if pacote_cliente:
            pacote_cliente.sessoes_restantes += 1
            pacote_cliente.ativo = True # Reativa se estava zerado
            db.session.add(pacote_cliente)
            
    db.session.commit()
    return redirect(url_for('agenda', data=agendamento.data_hora.strftime('%Y-%m-%d')))

# ROTA DA ABA FINANCEIRO
@app.route('/financeiro')
def financeiro():
    if 'manicure_id' not in session: return redirect(url_for('login'))
    manicure_id_logada = session['manicure_id']
    
    # 1. Entradas por vendas de pacotes/combos
    vendas_pacotes = ClientePacote.query.join(Pacote).filter(Pacote.manicure_id == manicure_id_logada).order_by(ClientePacote.data_compra.desc()).all()
    total_pacotes = sum(vp.pacote_comprado.valor_total for vp in vendas_pacotes)
    
    # 2. Entradas de atendimentos avulsos validados (pagos)
    avulsos_pagos = Agendamento.query.filter_by(
        manicure_id=manicure_id_logada, 
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
    if 'manicure_id' not in session:
        return redirect(url_for('login'))

    manicure_id_logada = session['manicure_id']
    
    if request.method == 'POST':
        # Captura os dados vindos do formulário
        nome = request.form.get('nome_servico')
        valor = float(request.form.get('valor').replace(',', '.')) # Trata vírgula decimal
        duracao = int(request.form.get('duracao_minutos'))
        
        # Cria o novo serviço atrelado à manicure logada
        novo_servico = Servico(
            manicure_id=manicure_id_logada,
            nome_servico=nome,
            valor=valor,
            duracao_minutos=duracao
        )
        
        db.session.add(novo_servico)
        db.session.commit()
        
        return redirect(url_for('servicos')) # Recarrega a página limpa
        
    # Se for GET, busca apenas os serviços dessa manicure
    lista_servicos = Servico.query.filter_by(manicure_id=manicure_id_logada).all()
    return render_template('servicos.html', servicos=lista_servicos)

@app.route('/agenda', methods=['GET', 'POST'])
def agenda():
    if 'manicure_id' not in session:
        return redirect(url_for('login'))

    manicure_id_logada = session['manicure_id']
    
    if request.method == 'POST':
        # Cadastro manual de agendamento pelo painel
        cliente_id = request.form.get('cliente_id')
        servico_id = request.form.get('servico_id')
        data_hora_str = request.form.get('data_hora') # Recebe 'YYYY-MM-DDTHH:MM'
        
        novo_agendamento = Agendamento(
            manicure_id=manicure_id_logada,
            cliente_id=cliente_id,
            servico_id=servico_id,
            data_hora=datetime.strptime(data_hora_str, '%Y-%m-%dT%H:%M'),
            status="Confirmado"
        )
        db.session.add(novo_agendamento)
        db.session.commit()
        
        # Redireciona de volta para o dia do agendamento criado
        data_foco = data_hora_str.split('T')[0]
        return redirect(url_for('agenda', data=data_foco))

    # Se for GET, filtra os agendamentos por dia
    # Se não passar data na URL (?data=2026-05-21), assume o dia de hoje
    data_url = request.args.get('data', datetime.now().strftime('%Y-%m-%d'))
    data_objeto = datetime.strptime(data_url, '%Y-%m-%d')
    
    # Define o início e o fim do dia para buscar no banco de dados
    inicio_dia = data_objeto.replace(hour=0, minute=0, second=0)
    fim_dia = data_objeto.replace(hour=23, minute=59, second=59)
    
    # Query buscando agendamentos do dia, ordenados pelo horário
    agendamentos_dia = Agendamento.query.filter(
        Agendamento.manicure_id == manicure_id_logada,
        Agendamento.data_hora >= inicio_dia,
        Agendamento.data_hora <= fim_dia
    ).order_by(Agendamento.data_hora.asc()).all()
    
    # Busca serviços e clientes para popular os campos de seleção (Select) do Modal
    lista_servicos = Servico.query.filter_by(manicure_id=manicure_id_logada).all()
    lista_clientes = Cliente.query.filter_by(manicure_id=manicure_id_logada).all()
    
    return render_template(
        'agenda.html', 
        agendamentos=agendamentos_dia, 
        data_selecionada=data_url,
        servicos=lista_servicos,
        clientes=lista_clientes
    )

@app.route('/pacotes', methods=['GET', 'POST'])
def pacotes():
    # Proteção de acesso
    if 'manicure_id' not in session:
        return redirect(url_for('login'))
        
    manicure_id_logada = session['manicure_id']
    
    if request.method == 'POST':
        # Captura os dados do modal
        nome = request.form.get('nome_pacote')
        valor = float(request.form.get('valor_total').replace(',', '.'))
        qtd = int(request.form.get('qtd_sessoes'))
        
        # Cria o combo no banco de dados
        novo_pacote = Pacote(
            manicure_id=manicure_id_logada,
            nome_pacote=nome,
            valor_total=valor,
            qtd_sessoes=qtd
        )
        
        db.session.add(novo_pacote)
        db.session.commit()
        
        return redirect(url_for('pacotes')) # Atualiza a tela
        
    # GET: Busca os pacotes criados por esta manicure
    lista_pacotes = Pacote.query.filter_by(manicure_id=manicure_id_logada).order_by(Pacote.nome_pacote.asc()).all()
    
    return render_template('pacotes.html', pacotes=lista_pacotes)

@app.route('/clientes', methods=['GET', 'POST'])
def clientes():
    if 'manicure_id' not in session:
        return redirect(url_for('login'))
        
    manicure_id_logada = session['manicure_id']
    
    if request.method == 'POST':
        nome = request.form.get('nome')
        whatsapp = request.form.get('whatsapp') 
        
        nova_cliente = Cliente(manicure_id=manicure_id_logada, nome=nome, whatsapp=whatsapp)
        db.session.add(nova_cliente)
        db.session.commit()
        return redirect(url_for('clientes'))
        
    # GET: Além das clientes, buscamos os pacotes da manicure para carregar no modal de vendas
    lista_clientes = Cliente.query.filter_by(manicure_id=manicure_id_logada).order_by(Cliente.nome.asc()).all()
    lista_pacotes = Pacote.query.filter_by(manicure_id=manicure_id_logada).order_by(Pacote.nome_pacote.asc()).all()
    
    return render_template('clientes.html', clientes=lista_clientes, pacotes=lista_pacotes)

@app.route('/vender_pacote', methods=['POST'])
def vender_pacote():
    if 'manicure_id' not in session:
        return redirect(url_for('login'))
        
    cliente_id = request.form.get('cliente_id')
    pacote_id = request.form.get('pacote_id')
    
    # 1. Busca o pacote para saber quantas sessões ele dá direito
    pacote = Pacote.query.get(pacote_id)
    
    if pacote:
        # 2. Cria o registro de saldo para a cliente
        nova_venda = ClientePacote(
            cliente_id=cliente_id,
            pacote_id=pacote_id,
            sessoes_restantes=pacote.qtd_sessoes, # Inicia com o total do combo (ex: 4)
            ativo=True
        )
        db.session.add(nova_venda)
        db.session.commit()
        
    return redirect(url_for('clientes'))

@app.route('/horarios', methods=['GET', 'POST'])
def horarios():
    if 'manicure_id' not in session:
        return redirect(url_for('login'))

    manicure_id_logada = session['manicure_id']
    dias_semana = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado', 'Domingo']

    if request.method == 'POST':
        # O formulário vai enviar dados para os 7 dias (0 a 6)
        for i in range(7):
            ativo = request.form.get(f'ativo_{i}') == 'on'
            hora_inicio = request.form.get(f'hora_inicio_{i}')
            hora_fim = request.form.get(f'hora_fim_{i}')
            almoco_inicio = request.form.get(f'almoco_inicio_{i}')
            almoco_fim = request.form.get(f'almoco_fim_{i}')

            # Busca se já existe regra para esse dia
            config = ConfigHorario.query.filter_by(manicure_id=manicure_id_logada, dia_semana=i).first()
            
            if not config:
                # Se não existir, cria um novo registro
                config = ConfigHorario(manicure_id=manicure_id_logada, dia_semana=i)
                db.session.add(config)
            
            # Atualiza os dados
            config.ativo = ativo
            config.hora_inicio = hora_inicio if hora_inicio else "08:00"
            config.hora_fim = hora_fim if hora_fim else "18:00"
            
            # Almoço é opcional. Se a manicure deixar em branco, salvamos None
            config.almoco_inicio = almoco_inicio if almoco_inicio else None
            config.almoco_fim = almoco_fim if almoco_fim else None

        db.session.commit()
        return redirect(url_for('horarios'))

    # GET: Busca as configurações salvas para preencher a tela
    configs = ConfigHorario.query.filter_by(manicure_id=manicure_id_logada).all()
    # Cria um dicionário para facilitar a busca no HTML
    mapa_configs = {c.dia_semana: c for c in configs}
    
    return render_template('horarios.html', dias_semana=dias_semana, mapa_configs=mapa_configs)

@app.route('/toggle_manicure/<int:id>', methods=['POST'])
@admin_required
def toggle_manicure(id):
    manicure = Manicure.query.get_or_404(id)
    
    # Inverte o status atual
    manicure.ativo = not manicure.ativo
    db.session.commit()
    
    status_str = "ativada" if manicure.ativo else "suspensa/desativada"
    flash(f'A conta de {manicure.nome} foi {status_str} com sucesso!')
    return redirect(url_for('painel_master'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        telefone = request.form.get('telefone')
        senha = request.form.get('senha')
        
        manicure = Manicure.query.filter_by(telefone_bot=telefone, senha=senha).first()
        
        if manicure:
            # BLOQUEIO CRÍTICO: Se a conta estiver desativada pelo admin, não deixa logar
            if not manicure.ativo:
                flash('Seu acesso está suspenso. Entre em contato com o administrador do sistema.')
                return render_template('login.html') # Devolve para a tela de login com o aviso
                
            # Se estiver ativa, segue o fluxo normal de sessão...
            session['manicure_id'] = manicure.id
            session['manicure_nome'] = manicure.nome
            return redirect(url_for('dashboard'))
            
        flash('Usuário ou senha incorretos.')
    return render_template('login.html')

@app.route('/meu_bot')
def meu_bot():
    if 'manicure_id' not in session: 
        return redirect(url_for('login'))
        
    # Passamos os dados necessários para o menu superior funcionar corretamente
    dados_dinamicos = {
        "nome_manicure": session.get('manicure_nome')
    }
    return render_template('meu_bot.html', dados=dados_dinamicos)

@app.route('/logout')
def logout():
    session.clear() # Limpa todos os dados da sessão
    return redirect(url_for('login'))

## ADMIN 

# Cadeado de Segurança
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('is_super_admin') != True:
            return redirect(url_for('login_master'))
        return f(*args, **kwargs)
    return decorated_function

# URL Secreta de Login Master (Ex: /mestre_do_saas)
@app.route('/mestre_do_saas', methods=['GET', 'POST'])
def login_master():
    if request.method == 'POST':
        senha = request.form.get('senha_master')
        # Mude esta senha para uma bem forte!
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
        
        # Cria a manicure
        nova = Manicure(nome=nome, telefone_bot=telefone, senha=senha)
        db.session.add(nova)
        db.session.commit()
        
        # Cria horários padrão para ela (Seg-Sex)
        for d in range(5):
            h = ConfigHorario(manicure_id=nova.id, dia_semana=d, hora_inicio="08:00", hora_fim="18:00")
            db.session.add(h)
        db.session.commit()
        
        flash(f'Conta de {nome} criada com sucesso!')
        return redirect(url_for('painel_master'))

    todas = Manicure.query.all()
    return render_template('painel_master.html', manicures=todas)

@app.route('/mudar_senha_manicure/<int:id>', methods=['POST'])
@admin_required
def mudar_senha_manicure(id):
    manicure = Manicure.query.get_or_404(id)
    nova_senha = request.form.get('nova_senha')
    
    if nova_senha:
        manicure.senha = nova_senha
        db.session.commit()
        flash(f'Senha da cliente {manicure.nome} alterada com sucesso!')
        
    return redirect(url_for('painel_master'))

@app.route('/logout_master')
def logout_master():
    session['is_super_admin'] = False
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)