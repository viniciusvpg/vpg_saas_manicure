from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Estabelecimento(db.Model): # Antiga classe Manicure
    __tablename__ = 'estabelecimentos'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    telefone_bot = db.Column(db.String(20), unique=True, nullable=False)
    senha = db.Column(db.String(100), nullable=False)
    ativo = db.Column(db.Boolean, default=True)
    
    # NOVO CAMPO: Define o tema do painel
    nicho = db.Column(db.String(50), default='manicure')
    
    # Relacionamentos
    servicos = db.relationship('Servico', backref='estabelecimento', lazy=True)
    clientes = db.relationship('Cliente', backref='estabelecimento', lazy=True)
    agendamentos = db.relationship('Agendamento', backref='estabelecimento', lazy=True)

class Servico(db.Model):
    __tablename__ = 'servicos'
    id = db.Column(db.Integer, primary_key=True)
    estabelecimento_id = db.Column(db.Integer, db.ForeignKey('estabelecimentos.id'), nullable=False)
    nome_servico = db.Column(db.String(100), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    duracao_minutos = db.Column(db.Integer, nullable=False) # Ex: 90 para 1h30m

class Cliente(db.Model):
    __tablename__ = 'clientes'
    id = db.Column(db.Integer, primary_key=True)
    estabelecimento_id = db.Column(db.Integer, db.ForeignKey('estabelecimentos.id'), nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    whatsapp = db.Column(db.String(20), nullable=False)
    historico_pacotes = db.relationship('ClientePacote', backref='cliente', lazy=True)

class Agendamento(db.Model):
    __tablename__ = 'agendamentos'
    id = db.Column(db.Integer, primary_key=True)
    estabelecimento_id = db.Column(db.Integer, db.ForeignKey('estabelecimentos.id'), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    servico_id = db.Column(db.Integer, db.ForeignKey('servicos.id'), nullable=False)
    data_hora = db.Column(db.DateTime, nullable=False)
    
    # NOVOS CAMPOS DE CONTROLE FINANCEIRO
    status = db.Column(db.String(20), default='Agendado') # 'Agendado', 'Concluído', 'Não Compareceu'
    tipo_pagamento = db.Column(db.String(20), default='Avulso') # 'Avulso' ou 'Pacote'
    pago = db.Column(db.Boolean, default=False)

    cliente = db.relationship('Cliente', backref='historico_agendamentos', lazy=True)
    servico = db.relationship('Servico', backref='agendamentos_deste_servico', lazy=True)

class Pacote(db.Model):
    __tablename__ = 'pacotes'
    id = db.Column(db.Integer, primary_key=True)
    estabelecimento_id = db.Column(db.Integer, db.ForeignKey('estabelecimentos.id'), nullable=False)
    nome_pacote = db.Column(db.String(100), nullable=False) # Ex: Combo 4x Mão
    valor_total = db.Column(db.Float, nullable=False)       # Ex: R$ 100,00
    qtd_sessoes = db.Column(db.Integer, nullable=False)     # Ex: 4 sessões
    
    # Opcional: Atrelar o pacote a um serviço específico (Ex: Só vale para "Pé e Mão")
    servico_id = db.Column(db.Integer, db.ForeignKey('servicos.id'), nullable=True) 
    servico = db.relationship('Servico', backref='pacotes_vinculados', lazy=True)
    
    # Relacionamento com as vendas
    vendas = db.relationship('ClientePacote', backref='pacote_comprado', lazy=True)

class ClientePacote(db.Model):
    __tablename__ = 'cliente_pacotes'
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    estabelecimento_id = db.Column(db.Integer, db.ForeignKey('estabelecimentos.id'), nullable=False)
    pacote_id = db.Column(db.Integer, db.ForeignKey('pacotes.id'), nullable=False)
    
    # É aqui que a mágica acontece: o saldo de sessões!
    sessoes_restantes = db.Column(db.Integer, nullable=False) 
    
    data_compra = db.Column(db.DateTime, default=datetime.utcnow)
    ativo = db.Column(db.Boolean, default=True) # Fica False quando as sessões zeram

class ConfigHorario(db.Model):
    __tablename__ = 'config_horarios'
    id = db.Column(db.Integer, primary_key=True)
    estabelecimento_id = db.Column(db.Integer, db.ForeignKey('estabelecimentos.id'), nullable=False)
    
    # 0 = Segunda, 1 = Terça, 2 = Quarta ... 6 = Domingo (Padrão do Python .weekday())
    dia_semana = db.Column(db.Integer, nullable=False) 
    
    hora_inicio = db.Column(db.String(5), nullable=False)  # Ex: "08:00"
    hora_fim = db.Column(db.String(5), nullable=False)     # Ex: "18:00"
    almoco_inicio = db.Column(db.String(5), nullable=True) # Ex: "12:00"
    almoco_fim = db.Column(db.String(5), nullable=True)    # Ex: "13:30"
    ativo = db.Column(db.Boolean, default=True)            # False se fechar nesse dia