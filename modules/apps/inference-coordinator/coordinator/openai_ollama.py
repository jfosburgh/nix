"""Pi-compatible chat API backed by guarded native Ollama requests.

This is translation, not token estimation. Every load/inference retains native
truncate=false/shift=false, fixed per-model context, and configured output caps.
Unsupported controls/features are rejected rather than silently discarded.
"""
from dataclasses import replace
import json
import time
import uuid

from .native_trial import NativeTrialProtocol
from .protocol import Admission, AdmissionError, json_object


def encode(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False).encode()


def messages_to_native(messages):
    if type(messages) is not list:
        raise AdmissionError(422, 'Expected messages array')
    result, names = [], {}
    for message in messages:
        if type(message) is not dict or set(message) - {'role','content','name','tool_calls',
                                                       'tool_call_id','reasoning_content'}:
            raise AdmissionError(422, 'Unsupported message feature')
        role = message.get('role')
        if role not in ('system','developer','user','assistant','tool'):
            raise AdmissionError(422, 'Unsupported message role')
        content = message.get('content')
        if content is None and role == 'assistant':
            content = ''
        if type(content) is list:
            if any(type(part) is not dict or set(part) != {'type','text'}
                   or part.get('type') != 'text' or type(part.get('text')) is not str for part in content):
                raise AdmissionError(422, 'Only text input is supported')
            content = ''.join(part['text'] for part in content)
        if type(content) is not str:
            raise AdmissionError(422, 'Expected text content')
        item = dict(role='system' if role=='developer' else role, content=content)
        if 'reasoning_content' in message:
            if type(message['reasoning_content']) is not str:
                raise AdmissionError(422, 'Invalid reasoning content')
            item['thinking'] = message['reasoning_content']
        if 'tool_calls' in message:
            calls = message['tool_calls']
            if type(calls) is not list:
                raise AdmissionError(422, 'Expected tool calls array')
            item['tool_calls'] = []
            for call in calls:
                if type(call) is not dict or call.get('type') != 'function' or type(call.get('function')) is not dict:
                    raise AdmissionError(422, 'Expected function tool call')
                function = call['function']
                name, arguments, identifier = function.get('name'), function.get('arguments'), call.get('id')
                if type(name) is not str or not name or type(identifier) is not str or not identifier:
                    raise AdmissionError(422, 'Tool call needs ID and name')
                if type(arguments) is str:
                    arguments = json_object(arguments.encode())
                if type(arguments) is not dict or identifier in names:
                    raise AdmissionError(422, 'Invalid tool call arguments/ID')
                names[identifier] = name
                item['tool_calls'].append(dict(function=dict(name=name, arguments=arguments)))
        if role == 'tool':
            identifier = message.get('tool_call_id')
            name = names.get(identifier) if type(identifier) is str else None
            if not name:
                raise AdmissionError(422, 'Unknown tool result ID')
            item['tool_name'] = name
        result.append(item)
    return result


class OllamaChatProtocol(NativeTrialProtocol):
    def admit(self, method, path, body):
        if (method,path)==('GET','/v1/models') and not body:
            return Admission('discovery',False,b'',upstream_path='/api/tags')
        if (method,path)!=('POST','/v1/chat/completions'):
            return super().admit(method,path,body)
        value = json_object(body)
        allowed = {'model','messages','stream','stream_options','max_tokens','max_completion_tokens',
                   'temperature','top_p','top_k','min_p','seed','stop','repeat_penalty','tools',
                   'tool_choice','reasoning_effort','response_format','n','store','parallel_tool_calls'}
        if set(value)-allowed:
            raise AdmissionError(422,'Unsupported chat request feature')
        if type(value.get('n',1)) is not int or value.get('n',1)!=1 or value.get('store',False) is not False:
            raise AdmissionError(422,'Multiple completions and storage are unsupported')
        if 'parallel_tool_calls' in value and value['parallel_tool_calls'] is not True:
            raise AdmissionError(422,'Sequential-only tool selection is unsupported')
        if value.get('tool_choice','auto') not in ('auto','none'):
            raise AdmissionError(422,'Only auto/none tool selection is supported')
        stream_options = value.get('stream_options',{})
        if (type(stream_options) is not dict or set(stream_options)-{'include_usage'}
                or type(stream_options.get('include_usage',False)) is not bool):
            raise AdmissionError(422,'Unsupported stream options')
        if 'max_tokens' in value and 'max_completion_tokens' in value:
            raise AdmissionError(422,'Choose one output limit')
        options = {key:value[key] for key in ('temperature','top_p','top_k','min_p','seed','stop','repeat_penalty') if key in value}
        maximum = value.get('max_completion_tokens',value.get('max_tokens'))
        if maximum is not None:
            options['num_predict'] = maximum
        effort = value.get('reasoning_effort','none')
        if effort not in ('none','off','minimal','low','medium','high','xhigh','max'):
            raise AdmissionError(422,'Unsupported reasoning effort')
        native = dict(model=value.get('model'), messages=messages_to_native(value.get('messages')),
                      stream=value.get('stream',False), think=effort not in ('none','off'), options=options)
        if 'tools' in value and value.get('tool_choice')!='none':
            native['tools'] = value['tools']
        if 'response_format' in value:
            fmt = value['response_format']
            if type(fmt) is not dict:
                raise AdmissionError(422,'Unsupported response format')
            if fmt.get('type')=='json_object' and set(fmt)=={'type'}:
                native['format'] = 'json'
            elif fmt.get('type')=='json_schema' and type(fmt.get('json_schema')) is dict and type(fmt['json_schema'].get('schema')) is dict:
                native['format'] = fmt['json_schema']['schema']
            else:
                raise AdmissionError(422,'Unsupported response format')
        admission = super().admit('POST','/api/chat',encode(native))
        return replace(admission,upstream_path='/api/chat',
                       response_adapter='openai-stream' if native['stream'] else 'openai-json')

    async def validate_input(self,path,admission):
        await super().validate_input('/api/chat' if path=='/v1/chat/completions' else path,admission)

    def discovery_response(self,path,body):
        if path!='/v1/models':
            return super().discovery_response(path,body)
        native = json.loads(super().discovery_response('/api/tags',body))
        return encode(dict(object='list',data=[dict(id=model['name'],object='model',owned_by='ollama')
                                               for model in native['models']]))


def usage(value):
    prompt, completion = value.get('prompt_eval_count'), value.get('eval_count')
    if type(prompt) is int and type(completion) is int and min(prompt,completion)>=0:
        return dict(prompt_tokens=prompt,completion_tokens=completion,total_tokens=prompt+completion)
    return None  # Do not manufacture token counts.


def tool_calls(message, *, streaming=False, offset=0):
    calls = message.get('tool_calls',[])
    if type(calls) is not list:
        raise ValueError('Invalid upstream tools')
    result = []
    for index,call in enumerate(calls,offset):
        function = call['function']
        arguments = function['arguments']
        if type(arguments) is not dict or type(function['name']) is not str:
            raise ValueError('Invalid upstream tool call')
        item = dict(id='call_'+uuid.uuid4().hex,type='function',
                    function=dict(name=function['name'],arguments=encode(arguments).decode()))
        if streaming:
            item['index'] = index
        result.append(item)
    return result


async def relay(upstream,response,request,*,request_id,streaming,idle):
    """Consume EOF before returning ownership; partial errors abort via caller."""
    import asyncio
    identifier,created = 'chatcmpl-'+request_id,int(time.time())
    async def write(value):
        async with asyncio.timeout(idle):
            await response.write(value)
    if not streaming:
        body = bytearray()
        async for chunk in upstream.content.iter_chunked(65536):
            body.extend(chunk)
            if len(body)>2*1024**2:
                raise ValueError('Native response bound exceeded')
        value = json_object(bytes(body))
        if value.get('done') is not True or 'error' in value:
            raise ValueError('Native completion unconfirmed')
        native = value['message']
        message = dict(role='assistant',content=native.get('content',''))
        if native.get('thinking'):
            message['reasoning_content'] = native['thinking']
        calls = tool_calls(native)
        if calls:
            message['tool_calls'] = calls
        finish = 'tool_calls' if calls else ('length' if value.get('done_reason')=='length' else 'stop')
        result = dict(id=identifier,object='chat.completion',created=created,model=value['model'],
                      choices=[dict(index=0,message=message,finish_reason=finish)])
        measured = usage(value)
        if measured is not None:
            result['usage'] = measured
        response.content_type = 'application/json'
        await response.prepare(request)
        await write(encode(result))
    else:
        response.content_type = 'text/event-stream'
        await response.prepare(request)
        terminal = False
        count = total = 0
        async for line in upstream.content:
            total += len(line)
            if len(line)>1024**2 or total>2*1024**2 or terminal:
                raise ValueError('Native stream bound/terminal violation')
            value = json_object(line)
            if 'error' in value:
                raise ValueError('Native stream failed')
            message = value.get('message',{})
            delta = dict(role='assistant')
            for source,target in (('content','content'),('thinking','reasoning_content')):
                if message.get(source):
                    delta[target] = message[source]
            calls = tool_calls(message,streaming=True,offset=count)
            count += len(calls)
            if calls:
                delta['tool_calls'] = calls
            terminal = value.get('done') is True
            finish = ('tool_calls' if count else ('length' if value.get('done_reason')=='length' else 'stop')) if terminal else None
            result = dict(id=identifier,object='chat.completion.chunk',created=created,model=value['model'],
                          choices=[dict(index=0,delta=delta,finish_reason=finish)])
            await write(b'data: '+encode(result)+b'\n\n')
            measured = usage(value)
            if terminal and measured is not None:
                await write(b'data: '+encode(dict(id=identifier,object='chat.completion.chunk',created=created,
                    model=value['model'],choices=[],usage=measured))+b'\n\n')
        if not terminal:
            raise ValueError('Native stream completion unconfirmed')
        await write(b'data: [DONE]\n\n')
    await response.write_eof()
