from datetime import datetime, timedelta
from app import app
from models import ConfigHorario, db, Manicure, Servico, Cliente, Agendamento

def popular_banco():
    # Entra no contexto do Flask para conseguir acessar o banco de dados
    with app.app_context():
        print("Iniciando a inserção de dados de teste...")

        # 1. Limpa o banco de dados atual (para você poder rodar o seed várias vezes sem duplicar)
        db.drop_all()
        db.create_all()

        # 2. Cria a nossa cliente número 1 (A dona do salão)
        ana = Manicure(nome="Ana Costa", telefone_bot="5547999990000", senha="123456")
        db.session.add(ana)
        db.session.commit()

        # === ADICIONE ESTE BLOCO PARA O EXPEDIENTE ===
        # Vamos cadastrar o horário dela para Terça (1), Quarta (2), Quinta (3) e Sexta (4)
        for dia in [1, 2, 3, 4]:
            expediente = ConfigHorario(
                manicure_id=ana.id,
                dia_semana=dia,
                hora_inicio="08:00",
                hora_fim="18:00",
                almoco_inicio="12:00",
                almoco_fim="13:30"
            )
            db.session.add(expediente)
        db.session.commit()

        # 3. Cadastra os Serviços (Cardápio do Bot)
        servico1 = Servico(manicure_id=ana.id, nome_servico="Pé e Mão Clássico", valor=60.00, duracao_minutos=90)
        servico2 = Servico(manicure_id=ana.id, nome_servico="Manutenção de Gel", valor=120.00, duracao_minutos=120)
        servico3 = Servico(manicure_id=ana.id, nome_servico="Spa dos Pés", valor=45.00, duracao_minutos=45)
        
        db.session.add_all([servico1, servico2, servico3])

        # 4. Cadastra as Clientes Finais
        cliente1 = Cliente(manicure_id=ana.id, nome="Maria Silva", whatsapp="5547988881111")
        cliente2 = Cliente(manicure_id=ana.id, nome="Juliana Souza", whatsapp="5547988882222")
        
        db.session.add_all([cliente1, cliente2])
        db.session.commit() # Commit para gerar os IDs dos serviços e clientes

        # 5. Cria Agendamentos para o dia de HOJE
        hoje = datetime.now()
        
        # Agendamento às 14:00
        agendamento1 = Agendamento(
            manicure_id=ana.id,
            cliente_id=cliente1.id,
            servico_id=servico1.id,
            data_hora=hoje.replace(hour=14, minute=0, second=0, microsecond=0),
            status="Confirmado"
        )

        # Agendamento às 16:00
        agendamento2 = Agendamento(
            manicure_id=ana.id,
            cliente_id=cliente2.id,
            servico_id=servico2.id,
            data_hora=hoje.replace(hour=16, minute=0, second=0, microsecond=0),
            status="Confirmado"
        )

        db.session.add_all([agendamento1, agendamento2])
        db.session.commit()

        print("✅ Banco de dados populado com sucesso!")
        print("Temos 1 Manicure, 3 Serviços, 2 Clientes e 2 Agendamentos criados.")

if __name__ == '__main__':
    popular_banco()