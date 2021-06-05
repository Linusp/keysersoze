import dash_core_components as dcc
import dash_bootstrap_components as dbc


def make_card_component(data, show_money=True, inverse=False):

    children = []
    for item in data:
        class_name = 'pt-0 mb-0'
        if item.get('color'):
            class_name = f'{class_name} {item["color"]}'

        cls = item['item_cls']
        if item['type'] == 'text':
            children.append(cls(item['content'], className=class_name))
        elif item['type'] == 'percent':
            if isinstance(item['content'], (float, int)):
                children.append(
                    cls(f'{100 * item["content"]:0.2f}%', className=class_name)
                )
            elif item['content'] is None:
                children.append(
                    cls('N/A', className=class_name)
                )
            else:
                children.append(cls(item["content"], className=class_name))
        elif item['type'] == 'money':
            if isinstance(item['content'], (float, int)):
                if show_money:
                    children.append(
                        cls(f'{item["content"]:0.2f} 元', className=class_name)
                    )
                else:
                    children.append(cls('***** 元', className=class_name))
            else:
                children.append(item["content"], className=class_name)
        elif item['type'] == 'amount':
            if isinstance(item['content'], (float, int)):
                if show_money:
                    children.append(
                        cls(f'{item["content"]:0.2f} 份', className=class_name)
                    )
                else:
                    children.append(cls('***** 份', className=class_name))
            else:
                children.append(item["content"], className=class_name)
        elif item['type'] == 'price':
            if isinstance(item['content'], (float, int)):
                children.append(
                    cls(f'{item["content"]:0.4f} 元', className=class_name)
                )
            else:
                children.append(cls(item["content"], className=class_name))
        elif item['type'] == 'figure':
            children.append(
                dcc.Graph(
                    figure=item['content'],
                    config={
                        'displayModeBar': False
                    }
                )
            )

    return dbc.Card(
        dbc.CardBody(children, className='px-0 py-0'),
        className='border-0',
        inverse=inverse
    )
