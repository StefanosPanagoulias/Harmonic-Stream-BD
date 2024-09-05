
import flask
import logging
import psycopg2
import time
import jwt
import itertools
from collections import defaultdict
from datetime import datetime, timedelta


app = flask.Flask(__name__)

global StatusCodes
StatusCodes = {
    'success': 200,
    'api_error': 400,
    'internal_error': 500
}

app.config['SECRET_KEY'] = 'e1646d21883af2d2b7d4759d222be389'


def flatten_list(nested_list):
    return list(itertools.chain.from_iterable(nested_list))


##########################################################
## CLASSES
##########################################################

class Table:
    def __init__(self, name, columns):
        self.name = name
        self.columns = columns

    # autenticação do usuário
    def token_required(self):
        conn = db_connection()
        cur = conn.cursor()

        token = None
        if 'Authorization' in flask.request.headers:
            token = flask.request.headers['Authorization']

        if not token:
            return {"status": StatusCodes['api_error'], "results": "Token missing"}

        token = token.split(" ")[1]
        data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])

        try:
            cur.execute("SELECT * FROM usuario WHERE email = %s", (data['email'],))
            current_user = cur.fetchone()
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"Token - error: {error}")
            current_user = None
        finally:
            if conn is not None:
                conn.close()

        return {"status": StatusCodes['api_error'] if current_user is None else StatusCodes['success'],
                "results": current_user}

    def isAdmin(self, id):
        conn = db_connection()
        cur = conn.cursor()
        try:
            logger.info(f"id: {id}")
            cur.execute("SELECT * FROM admin WHERE usuario_id = %s", (id,))
            row = cur.fetchone()
            logger.info(f"row: {row}")

        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f'error: {error}')
            logger.error(f"Exception: {Exception}")
            row = None
        finally:
            if conn is not None:
                conn.close()
        return row

    def isArtist(self, id):
        conn = db_connection()
        cur = conn.cursor()
        try:
            logger.info(f"id: {id}")
            cur.execute("SELECT * FROM artist WHERE usuario_id = %s", (id,))
            row = cur.fetchone()
            logger.info(f"row: {row}")
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f'error: {error}')
            logger.error(f"Exception: {Exception}")
            row = None
        finally:
            if conn is not None:
                conn.close()
        return row
    
    def isConsumer(self, id):
        conn = db_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
            SELECT *
            FROM consumer
            WHERE usuario_id = %s
            """, (id,))
            row = cur.fetchone()
            if row is None:
                return None
            else:
                return row
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f'error: {error}')
            logger.error(f"Exception: {Exception}")
            response = {"status": StatusCodes['internal_error'], "errors": str(error)}
        finally:
            if conn is not None:
                conn.close()

    def create(self, params={}):
        response = []

        conn = db_connection()
        cur = conn.cursor()

        for column in self.columns:
            if column not in params.keys():
                response.append(f"{column} not in payload")

        if len(response) > 0:
            return {"status": StatusCodes['api_error'], "errors": response}

        value_string = ("%s," * len(self.columns))[:-1:]
        statement = f"INSERT INTO {self.name} ({','.join(self.columns)}) VALUES ({value_string})"

        values = [params[column] for column in self.columns]
        try:
            cur.execute(statement, values)
            logger.info(f"self.cur: {cur}")
            logger.info(f"self.conn: {conn}")
            response = {"status": StatusCodes['success'], "results": f"Row Inserted into {self.name}"}
            conn.commit()
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f'error: {error}')
            response = {"status": StatusCodes['internal_error'], "errors": str(error)}

            conn.rollback()
        finally:
            if conn is not None:
                conn.close()
        return response

    def show(self, id):
        conn = db_connection()
        cur = conn.cursor()

        try:
            cur.execute("SELECT * FROM %s WHERE id = %s", (self.name, id))
            rows = cur.fetchall()

            response = {"status": StatusCodes['success'], "results": str(rows)}
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f'error: {error}')
            logger.error(f"Exception: {Exception}")
            response = {"status": StatusCodes['internal_error'], "errors": str(error)}
        finally:
            if conn is not None:
                conn.close()

        return response


class User(Table):
    def __init__(self):
        super().__init__("usuario", ["username", "email", "password", "address"])

    def register(self, table, table_columns, params):
        response = []

        for column in self.columns:
            if column not in params.keys():
                response.append(f"{column} not in payload")

        for column in table_columns:
            if column not in params.keys():
                response.append(f"{column} not in payload")

        if len(response) > 0:
            return {"status": StatusCodes['api_error'], "errors": response}

        conn = db_connection()
        cur = conn.cursor()

        value_string = ("%s," * len(self.columns))[:-1:]
        statement = f"INSERT INTO {self.name} ({','.join(self.columns)}) VALUES ({value_string}) RETURNING id"
        values = [params[column] for column in self.columns]

        table_values = [params[column] for column in table_columns]

        table_columns.append('usuario_id')
        table_vs = ("%s," * len(table_columns))[:-1:]
        table_statement = f"INSERT INTO {table} ({','.join(table_columns)}) VALUES ({table_vs})"

        try:
            cur.execute(statement, values)
            logger.info(f"statement: {statement}")
            logger.info(f"values: {values}")
            user_id = cur.fetchone()
            table_values.append(user_id)

            cur.execute(table_statement, table_values)
            conn.commit()

            response = {"status": StatusCodes['success'], "response": f"Row inserted into {table}"}
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"error: {error}")

            response = {"status": StatusCodes['api_error'], "errors": str(error)}
            conn.rollback()
        return response

    def add_user(self):
        current_user = self.token_required()
        payload = flask.request.get_json()
        logger.info(f"PAYLOAD: {payload}")

        role = payload.pop('role', None)

        if role not in ['consumer', 'artist']:
            response = {"status": StatusCodes['api_error'], "errors": "Role field must be in [consumer, artist]"}
            return flask.jsonify(response)

        if role != 'consumer' and current_user["status"] == StatusCodes['api_error']:
            response = {"status": StatusCodes['api_error'],
                        "errors": current_user.get('errors') or "Must be logged in to create non consumers"}
            return flask.jsonify(response)
        
        if role == 'consumer' and current_user["status"] != StatusCodes['api_error']:
            consumer_user = self.isConsumer(current_user['results'][4])
            if consumer_user is not None and consumer_user[0] > datetime.now():
                payload['songs'] = []  # Adicionar músicas à playlist, se necessário
                response = self.create_playlist()

        logger.info(f"current_user: {current_user}")
        logger.info(f"current_user['results'][4]: {current_user['results'][4]}")

        if current_user.get('status') == StatusCodes['api_error']:
            isAdmin = False
        else:
            isAdmin = self.isAdmin(current_user['results'][4]) is not None

        logger.info(f"isAdmin: {isAdmin}")
        logger.info(f"current_user: {current_user}")

        if role == 'consumer':
            payload['subscription_time'] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            response = self.register('consumer', ['subscription_time'], payload)

        elif role == 'artist':
            response = self.register('artist', ['stagename'], payload)

        return flask.jsonify(response)

    def get_user(self, id):
        return flask.jsonify(self.show(id))

    def login(self):
        conn = db_connection()
        cur = conn.cursor()

        payload = flask.request.get_json()
        logger.info(f"payload: {payload}")

        if not payload.get('email') or not payload.get('password'):
            response = {'status': StatusCodes['api_error'], 'results': 'email and password are required'}
            return flask.jsonify(response)

        try:
            cur.execute('SELECT email FROM usuario WHERE email = %s AND password = %s',
                        (payload['email'], payload['password']))
            row = cur.fetchone()

            if row is None:
                response = {'status': StatusCodes['api_error'], 'results': 'Wrong email or password'}
            else:
                token = jwt.encode({'email': row[0]}, app.config['SECRET_KEY'])
                response = {'token': token, 'status': StatusCodes['success']}
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(error)
            response = {'status': StatusCodes['internal_error'], 'errors': str(error)}

        finally:
            if conn is not None:
                conn.close()

        return flask.jsonify(response)

    def show(self, id):
        conn = db_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
            SELECT artist.stagename, artist_music.music_ismn,position.album_id, position_playlist.playlist_id
            FROM artist
            LEFT JOIN artist_music ON artist.usuario_id = artist_music.artist_usuario_id
            LEFT JOIN position ON artist_music.music_ismn = position.music_ismn
            LEFT JOIN position_playlist ON artist_music.music_ismn = position_playlist.music_ismn
            WHERE artist.usuario_id = %s
            """, (id,))
            rows = cur.fetchall()

            groups = defaultdict(lambda: {'name': '', 'song_ids': [], 'album_ids': [], 'playlist_ids': []})
            for name, song_id, album_id, playlist_id in rows:
                groups[name]['name'] = name
                if song_id is not None:
                    groups[name]['song_ids'].append(song_id)
                if album_id is not None:
                    groups[name]['album_ids'].append(album_id)
                if playlist_id is not None:
                    groups[name]['playlist_ids'].append(playlist_id)

            # Extract the lists of song_ids, album_ids, and playlist_ids from the grouped items
            results = {}
            for group in groups.values():
                results[group['name']] = {
                    'song_ids': list(set(group['song_ids'])),
                    'album_ids': list(set(group['album_ids'])),
                    'playlist_ids': list(set(group['playlist_ids']))
                }

            response = {"status": StatusCodes['success'], "results": str(results)}
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f'error: {error}')
            logger.error(f"Exception: {Exception}")
            response = {"status": StatusCodes['internal_error'], "errors": str(error)}
        finally:
            if conn is not None:
                conn.close()

        return response

    def get_subs_info(self, subs_time):
        conn = db_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
            SELECT id,price
            FROM subscription
            WHERE subs_time = %s
            """, (subs_time,))
            row = cur.fetchone()
            if row is None:
                result = None
            else:
                result = row
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f'error: {error}')
            logger.error(f"Exception: {Exception}")
            result = None
        finally:
            if conn is not None:
                conn.close()
        return result

    def subscribe(self):
        current_user = self.token_required()

        columns = ['period', 'cards']
        
        if current_user.get('status') == StatusCodes['api_error']:
            response = {'status': StatusCodes['api_error'], 'results': 'consumer must be logged in to subscribe'}
            return flask.jsonify(response)
        
        consumer_user = self.isConsumer(current_user['results'][4])
        
        if consumer_user is None:
            response = {'status': StatusCodes['api_error'], 'results': 'only consumers are allowed to subscribe'}
            return flask.jsonify(response)
        
        payload = flask.request.get_json()
        
        logger.info(f"PAYLOAD: {payload}")

        response = []
        for column in columns:
            if column not in payload:
                response.append(f'{column} is required')
        
        if len(response) > 0:
            response = {'status': StatusCodes['api_error'], 'results': response}
            return flask.jsonify(response)
        
        conn = db_connection()
        cur = conn.cursor()
        dict = {"month": 1, "quarter": 3, "semester": 6}
        value = dict.get(payload['period'])
        if value is None:
            response = {'status': StatusCodes['api_error'], 'results': 'period must be month, quarter or semester'}
            return flask.jsonify(response)

        subs_id, price = self.get_subs_info(value)
        logger.info(f"subs_id: {subs_id}, price: {price} ASHUASHUSH")
        if subs_id is None:
            response = {'status': StatusCodes['api_error'], 'results': 'subscription not found'}
            return flask.jsonify(response)
        
        dt = consumer_user[0]


        if dt > datetime.now():
            dt += timedelta(weeks=4*value)
        else:
            dt = datetime.now() + timedelta(weeks=4*value)

        try:
            response = None
            for card in payload['cards']:
                cur.execute("""
                SELECT saldo FROM card WHERE id = %s AND consumer_usuario_id = %s AND expires_at > now()
                """, (card, current_user['results'][4]))
                row = cur.fetchone()
                if row is None:
                    response = {'status': StatusCodes['api_error'], 'results': 'card not found or expired'}
                    break
                #verify if saldo >= price
                if row[0] < price:
                    cur.execute("""
                    UPDATE card SET saldo = 0 WHERE id = %s
                    """, (card,))
                    price -= row[0]
                    cur.execute("""
                    INSERT INTO payment (purchasedate, card_id, subscription_id) VALUES (%s, %s, %s)
                    """, (datetime.now(), card, subs_id))
                else:
                    cur.execute("""
                    UPDATE card SET saldo = saldo - %s WHERE id = %s
                    """, (price, card))
                    price = 0
                    cur.execute("""
                    INSERT INTO payment (purchasedate, card_id, subscription_id) VALUES (%s, %s, %s)
                    """, (datetime.now(), card, subs_id))
                    break
            if price > 0 and response is None:
                conn.rollback()
                response = {'status': StatusCodes['api_error'], 'results': 'insufficient funds'}
                
            elif response is None:
                cur.execute("""
                UPDATE consumer SET Subscription_Time = %s WHERE usuario_id = %s
                """, (dt,current_user['results'][4]))
                conn.commit()
                response = {'status': StatusCodes['success'], 'results': 'subscription successful'}
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f'error: {error}')
            logger.error(f"Exception: {Exception}")
            conn.rollback()
            response = {'status': StatusCodes['internal_error'], 'errors': str(error)}
        finally:
            if conn is not None:
                conn.close()
        return flask.jsonify(response)
    
    def create_playlist(self):
        current_user = self.token_required()

        if current_user.get('status') == StatusCodes['api_error']:
            response = {'status': StatusCodes['api_error'], 'results': 'user must be logged in to create a playlist'}
            return flask.jsonify(response)

        consumer_user = self.isConsumer(current_user['results'][4])

        if consumer_user is None:
            response = {'status': StatusCodes['api_error'], 'results': 'only premium consumers are allowed to create a playlist'}
            return flask.jsonify(response)

        if consumer_user[0] <= datetime.now():
            response = {'status': StatusCodes['api_error'], 'results': 'subscription has expired'}
            return flask.jsonify(response)

        payload = flask.request.get_json()
        logger.info(f"PAYLOAD: {payload}")

        response = []
        if 'name' not in payload.keys():
            response.append("name not in payload")

        if 'isprivate' not in payload.keys():
            response.append("isprivate not in payload")
        elif payload['isprivate'] != 'public' and payload['isprivate'] != 'private':
            response.append("visibility must be 'public' or 'private'")

        if len(response) > 0:
            response = {'status': StatusCodes['api_error'], 'results': response}
            return flask.jsonify(response)

        conn = db_connection()
        cur = conn.cursor()

        try:
            # Inserir a playlist
            cur.execute("INSERT INTO playlist (name, isprivate, usuario_id) VALUES (%s, %s, %s) RETURNING id",
                        (payload['name'], payload['isprivate'] == 'private', current_user['results'][4]))
            playlist_id = cur.fetchone()[0]  # Obter o ID da playlist recém-criada

            # Verificar se há músicas para associar à playlist
            if 'songs' in payload.keys():
                # Criar registros na tabela position_playlist para cada música na playlist
                position = 1
                for music_ismn in payload['songs']:
                    cur.execute("INSERT INTO position_playlist (pos, playlist_id, music_ismn) VALUES (%s, %s, %s)",
                                (position, playlist_id, music_ismn))
                    position += 1

            conn.commit()
            response = {"status": StatusCodes['success'], "response": "Playlist created successfully"}
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"error: {error}")
            response = {"status": StatusCodes['api_error'], "errors": str(error)}
            conn.rollback()
        finally:
            conn.close()

        return flask.jsonify(response)
        





class Music(Table):
    def __init__(self):
        super().__init__('music', ['ismn', 'name', 'duration', 'genre', 'releasedate', 'recordlabel_id', 'artist_usuario_id'])

    def create(self, cur=None, conn=None, payload=None):
        current_user = self.token_required()

        if current_user.get('status') == StatusCodes['api_error']:
            response = {'status': StatusCodes['api_error'], 'results': 'user must be logged in to create Music'}
            return flask.jsonify(response)

        artist_user = self.isArtist(current_user['results'][4])

        if artist_user is None:
            response = {'status': StatusCodes['api_error'], 'results': 'only artists are allowed to create music'}
            return flask.jsonify(response)

        if payload is None:
            payload = flask.request.get_json()

        logger.info(f"PAYLOAD: {payload}")

        payload['artist_usuario_id'] = current_user['results'][4]

        if payload.get('other_artists') is None:
            payload['other_artists'] = []
        payload['other_artists'].append(payload['artist_usuario_id'])

        response = []
        for column in self.columns:
            if column not in payload.keys():
                response.append(f"{column} not in payload")

        if len(response) > 0:
            response = {'status': StatusCodes['api_error'], 'results': response}
            return flask.jsonify(response)

        conn_was_none = conn is None

        if conn is None:
            conn = db_connection()
            cur = conn.cursor()

        value_string = ("%s," * len(self.columns))[:-1:]
        statement = f"INSERT INTO {self.name} ({','.join(self.columns)}) VALUES ({value_string}) RETURNING ismn"
        values = [payload[column] for column in self.columns]

        artist_string = ("(%s, %s)," * len(payload['other_artists']))[:-1:]
        artist_statement = f"INSERT INTO artist_music (artist_usuario_id, music_ismn) VALUES {artist_string}"

        try:
            cur.execute(statement, values)
            logger.info(f"statement: {statement}")
            logger.info(f"values: {values}")
            ismn = cur.fetchone()

            artist_values = flatten_list([[artist, ismn] for artist in payload['other_artists']])
            logger.info(f"artist_values: {artist_values}")

            cur.execute(artist_statement, artist_values)
            if conn_was_none:
                conn.commit()

            response = {"status": StatusCodes['success'], "response": f"Row inserted into {self.name}"}
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"error: {error}")

            response = {"status": StatusCodes['api_error'], "errors": str(error)}

            if conn_was_none:
                conn.rollback()
        finally:
            if conn is not None and conn_was_none:
                conn.close()

        return flask.jsonify(response)

    def show(self, keyword):
        conn = db_connection()
        cur = conn.cursor()

        try:
            cur.execute("""SELECT music.name, artist.stagename, position.album_id
                    FROM music
                    INNER JOIN artist_music ON music.ismn = artist_music.music_ismn
                    INNER JOIN artist ON artist_music.artist_usuario_id = artist.usuario_id
                    LEFT JOIN position ON music.ismn = position.music_ismn
                    WHERE LOWER(music.name) LIKE LOWER(%(keyword)s)""", {'keyword': '%{}%'.format(keyword)})
            rows = cur.fetchall()

            groups = defaultdict(lambda: {'title': '', 'artists': [], 'albums': []})
            for title, artist, album in rows:
                groups[title]['title'] = title
                if artist is not None:
                    groups[title]['artists'].append(artist)
                if album is not None:
                    groups[title]['albums'].append(album)

            # Extract the lists of artists and albums from the grouped items
            results = {}
            for group in groups.values():
                results[group['title']] = {
                    'artists': group['artists'],
                    'albums': group['albums']
                }

            response = {"status": StatusCodes['success'], "results": str(results)}
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f'error: {error}')
            logger.error(f"Exception: {Exception}")
            response = {"status": StatusCodes['internal_error'], "errors": str(error)}
        finally:
            if conn is not None:
                conn.close()

        return response

    def isArtistsMusic(self, ismn, id):
        conn = db_connection()
        cur = conn.cursor()

        response = ''

        try:
            cur.execute("SELECT * FROM music where ismn = %s", (ismn,))
            row = cur.fetchone()
            if row is None:
                status = "NOSONG"
            else:
                cur.execute("SELECT * FROM artist_music WHERE music_ismn = %s AND artist_usuario_id = %s", (ismn, id))
                row = cur.fetchone()

                status = "NOARTIST" if row is None else "MATCH"
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"error: {error}")

            response = error
        return {'status': status, 'results': response}
    

    def comment(self, song_id):
        current_user = self.token_required()

        if current_user.get('status') == StatusCodes['api_error']:
            response = {'status': StatusCodes['api_error'], 'results': 'user must be logged in to comment on music'}
            return flask.jsonify(response)
        
        consumer_user = self.isConsumer(current_user['results'][4])
        if consumer_user is None:
            response = {'status': StatusCodes['api_error'], 'results': 'only consumers are allowed to comment on music'}
            return flask.jsonify(response)
        

        payload = flask.request.get_json()
        logger.info(f"PAYLOAD: {payload}")

        response = []
        if 'comment' not in payload.keys():
            response.append("comment not in payload")

        if len(response) > 0:
            response = {'status': StatusCodes['api_error'], 'results': response}
            return flask.jsonify(response)

        conn = db_connection()
        cur = conn.cursor()

        try:
            cur.execute("INSERT INTO comment (music_ismn, consumer_usuario_id, comment) VALUES (%s, %s, %s)", (song_id, current_user['results'][4], payload['comment']))
            conn.commit()
            response = {"status": StatusCodes['success'], "response": f"Row inserted into comment"}
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"error: {error}")

            response = {"status": StatusCodes['api_error'], "errors": str(error)}
            conn.rollback()
        finally:
            conn.close()

        return flask.jsonify(response)
    
    def reply(self, song_id, comment_id):
        current_user = self.token_required()

        if current_user.get('status') == StatusCodes['api_error']:
            response = {'status': StatusCodes['api_error'], 'results': 'user must be logged in to comment on music'}
            return flask.jsonify(response)
        
        consumer_user = self.isConsumer(current_user['results'][4])
        if consumer_user is None:
            response = {'status': StatusCodes['api_error'], 'results': 'only consumers are allowed to comment on music'}
            return flask.jsonify(response)
        

        payload = flask.request.get_json()
        logger.info(f"PAYLOAD: {payload}")

        response = []
        if 'comment' not in payload.keys():
            response.append("comment not in payload")
            
        if len(response) > 0:
            response = {'status': StatusCodes['api_error'], 'results': response}
            return flask.jsonify(response)

        conn = db_connection()
        cur = conn.cursor()

        try:
            cur.execute("SELECT * FROM comment WHERE id = %s AND music_ismn = %s", (comment_id, song_id))
            row = cur.fetchone()
            if row is None:
                response = {"status": StatusCodes['api_error'], "errors": "THe id is not from this song"}
            else:
                cur.execute("INSERT INTO comment (music_ismn, consumer_usuario_id, comment) VALUES (%s, %s, %s) returning id", (song_id, current_user['results'][4], payload['comment']))
                row = cur.fetchone()
                cur.execute("INSERT INTO comment_comment (comment_id, comment_id1) VALUES (%s, %s)", (row[0], comment_id))
                conn.commit()
                response = {"status": StatusCodes['success'], "response": f"Row inserted into comment"}
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"error: {error}")

            response = {"status": StatusCodes['api_error'], "errors": str(error)}
            conn.rollback()
        finally:
            conn.close()

        return flask.jsonify(response)
    

    def play_song(self, ismn):
        current_user = self.token_required()

        if current_user.get('status') == StatusCodes['api_error']:
            response = {'status': StatusCodes['api_error'], 'results': 'user must be logged in to play a song'}
            return flask.jsonify(response)
        
        if self.isConsumer(current_user['results'][4]) is None:
            response = {'status': StatusCodes['api_error'], 'results': 'only consumers are allowed to play a song'}
            return flask.jsonify(response)

        conn = db_connection()
        cur = conn.cursor()

        try:
            # Insert into playedsongs table
            cur.execute("INSERT INTO playedsongs (music_ismn, consumer_usuario_id, listened_at) VALUES (%s, %s, now())",
                        (ismn, current_user['results'][4]))
            conn.commit()

            # Update top playlist
            top_playlist = self.update_top_playlist(current_user['results'][4], cur)
            response = {"status": StatusCodes['success'], "response": "Song played successfully", "top_playlist": top_playlist}
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"error: {error}")

            response = {"status": StatusCodes['api_error'], "errors": str(error)}
            conn.rollback()
        finally:
            conn.close()

        return flask.jsonify(response)

    def update_top_playlist(self, user_id, cur):
        try:
            cur.execute("""
            SELECT music_ismn, COUNT(*) as play_count
            FROM playedsongs
            WHERE consumer_usuario_id = %s
            GROUP BY music_ismn
            ORDER BY play_count DESC
            LIMIT 10
            """, (user_id,))
            rows = cur.fetchall()

            top_playlist = defaultdict(int)
            for music_ismn, play_count in rows:
                top_playlist[music_ismn] = play_count

            return dict(top_playlist)
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"error: {error}")
            return {}
        
    #function to shwo the number of songs played per month and genre in the past 12 months, just one sql query should be used to obtain the informations
    def songs_played_per_month(self):
        current_user = self.token_required()

        if current_user.get('status') == StatusCodes['api_error']:
            response = {'status': StatusCodes['api_error'], 'results': 'user must be logged in to play a song'}
            return flask.jsonify(response)
        
        if self.isConsumer(current_user['results'][4]) is None:
            response = {'status': StatusCodes['api_error'], 'results': 'only consumers are allowed to play a song'}
            return flask.jsonify(response)

        conn = db_connection()
        cur = conn.cursor()

        try:
            # Insert into playedsongs table
            cur.execute("SELECT EXTRACT(MONTH FROM p.listened_at) as month, m.genre, COUNT(*) as play_count FROM playedsongs p JOIN music m ON p.music_ismn = m.ismn WHERE p.consumer_usuario_id = %s GROUP BY month, m.genre ORDER BY month DESC LIMIT 12;", (current_user['results'][4],))
            rows = cur.fetchall()
            aux = []
            for row in rows:
                aux.append({"month": row[0], "genre": row[1], "playback": row[2]})

            response = {"status": StatusCodes['success'], "response": aux}
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"error: {error}")

            response = {"status": StatusCodes['api_error'], "errors": str(error)}
            conn.rollback()
        finally:
            conn.close()

        return flask.jsonify(response)



class Album(Table):
    def __init__(self):
        super().__init__('album', ['name', 'releasedate'])

    def create(self):
        current_user = self.token_required()

        if current_user.get('status') == StatusCodes['api_error']:
            response = {'status': StatusCodes['api_error'], 'results': 'user must be logged in to create Album'}
            return flask.jsonify(response)

        artist_user = self.isArtist(current_user['results'][4])

        if artist_user is None:
            response = {'status': StatusCodes['api_error'], 'results': 'only artists are allowed to create Album'}
            return flask.jsonify(response)

        payload = flask.request.get_json()
        logger.info(f"PAYLOAD: {payload}")

        response = []
        for column in self.columns:
            if column not in payload.keys():
                response.append(f"{column} not in payload")

        for song in payload['songs']:
            if 'position' not in song.keys():
                response.append(f"position not in payload for {song['ismn']}")

        if len(response) > 0:
            response = {'status': StatusCodes['api_error'], 'results': response}
            return flask.jsonify(response)

        value_string = ("%s," * len(self.columns))[:-1:]
        statement = f"INSERT INTO {self.name} ({','.join(self.columns)}) VALUES ({value_string}) RETURNING id"
        values = [payload[column] for column in self.columns]

        music_table = Music()

        conn = db_connection()
        cur = conn.cursor()

        try:
            cur.execute(statement, values)
            row = cur.fetchone()

            cur.execute("INSERT INTO album_artist (album_id, artist_usuario_id) VALUES (%s, %s)",
                        (row[0], current_user['results'][4]))

            response = {'status': StatusCodes['success'], 'results': 'Added row into Album'}

            for song in payload['songs']:
                logger.info(f"Logging song: {song}")
                song_check = music_table.isArtistsMusic(song['ismn'], current_user['results'][4])

                if song_check['status'] is None:
                    response = {'status': StatusCodes['internal_error'], 'results': song_check['results']}
                    break
                elif song_check['status'] == 'NOARTIST':
                    response = {'status': StatusCodes['api_error'], 'results': 'Artist does not participate in song'}
                    break
                elif song_check['status'] == 'NOSONG':
                    res = music_table.create(cur=cur, conn=conn, payload=song).get_json()

                    if res['status'] != StatusCodes['success']:
                        response = res
                        break
                cur.execute("INSERT INTO position (position, album_id, music_ismn) VALUES (%s, %s, %s)",
                            (song['position'], row[0], song['ismn']))

            if response.get('status') == StatusCodes['api_error'] or response.get('status') == StatusCodes[
                'internal_error']:
                conn.rollback()
            else:
                conn.commit()

        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"error: {error}")

            response = {"status": StatusCodes['api_error'], "results": str(error)}

            conn.rollback()
        finally:
            if conn is not None:
                conn.close()
        return flask.jsonify(response)


class Card(Table):
    def __init__(self):
        super().__init__('card', ['admin_usuario_id', 'expires_at', 'saldo', 'valor', 'consumer_usuario_id'])

    def create(self):
        current_user = self.token_required()
        if current_user.get('status') == StatusCodes['api_error']:
            response = {'status': StatusCodes['api_error'], 'results': 'admin must be logged in to create a card'}
            return flask.jsonify(response)

        admin_user = self.isAdmin(current_user['results'][4])
        if admin_user is None:
            response = {'status': StatusCodes['api_error'], 'results': 'only admins are allowed to create Cards'}
            return flask.jsonify(response)
   
        payload = flask.request.get_json()

        logger.info(f"PAYLOAD: {payload}")

        responses = []

        conn = db_connection()
        cur = conn.cursor()

        processed_ids = []

        if "amount" not in payload.keys():
            response = {'status': StatusCodes['api_error'], 'results': 'amount not in payload'}
            return flask.jsonify(response)
        
        #verify that payload cards is not null
        if "cards" not in payload.keys():
            response = {'status': StatusCodes['api_error'], 'results': 'cards not in payload'}
            return flask.jsonify(response)
        
        if payload['amount'] != len(payload['cards']):
            response = {'status': StatusCodes['api_error'], 'results': 'amount does not match number of cards'}
            return flask.jsonify(response)
        
        for card_payload in payload["cards"]:
            response = []
            card_payload['admin_usuario_id'] = current_user['results'][4]
            for column in self.columns:
                if column not in card_payload.keys() and column != 'saldo':
                    response.append(f"{column} not in payload")

            # Check the 'valor' field
            valor = card_payload.get('valor')
            if valor not in ['10', '25', '50']:
                response.append(f"Invalid valor: {valor}. Valor must be '10', '25', or '50'.")
            if len(response) > 0:
                responses.append({'status': StatusCodes['api_error'], 'results': response})
                return flask.jsonify(responses)

            card_payload['saldo'] = valor
            # Set the 'saldo' value to be the same as 'valor'

        value_string = ("%s," * len(self.columns))[:-1:]
        statement = f"INSERT INTO {self.name} ({','.join(self.columns)}) VALUES ({value_string}) RETURNING id"

        try:
            for card_payload in payload["cards"]:
                values = [card_payload[column] for column in self.columns]
                cur.execute(statement, values)
                logger.info(f"statement: {statement}")
                logger.info(f"values: {values}")
                id = cur.fetchone()[0] 

                processed_ids.append(id)

                card_values = flatten_list([[card, id] for card in card_payload])
                logger.info(f"card_values: {card_values}")
            response = {'status': StatusCodes['success'], 'results': processed_ids}
            conn.commit()
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"error: {error}")
            response = ({"status": StatusCodes['api_error'], "errors": str(error)})
            conn.rollback()
        finally:
            if conn is not None:
                conn.close()

        return flask.jsonify(response)







##########################################################
## DATABASE ACCESS
##########################################################

def db_connection():
    db = psycopg2.connect(
        user='postgres',
        password='postgres',
        host='127.0.0.1',
        port='5432',
        database='Teste'
    )

    return db


##########################################################
## ENDPOINTS
##########################################################

@app.route('/usuarios/<id>', methods=['GET'])
def get_user(id):
    return User().get_user(id)


@app.route('/usuarios/', methods=['POST'])
def add_user():
    return User().add_user()


@app.route('/usuarios/', methods=['PUT'])
def login():
    return User().login()


@app.route('/song/', methods=['POST'])
def add_song():
    return Music().create()


@app.route('/album/', methods=['POST'])
def add_album():
    return Album().create()


@app.route('/usuarios/', methods=['GET'])
def get_all_users():
    conn = db_connection()
    cur = conn.cursor()

    try:
        cur.execute('SELECT id FROM usuario')
        rows = cur.fetchall()

        response = {"status": StatusCodes['success'], "response": str(rows)}
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f'GET /departments - error: {error}')
        response = {'status': StatusCodes['internal_error'], 'errors': str(error)}

    finally:
        if conn is not None:
            conn.close()

    return flask.jsonify(response)


@app.route('/song/<keyword>', methods=['GET'])
def get_all_songs(keyword):
    return Music().show(keyword)


@app.route('/artist_info/<artist_id>', methods=['GET'])
def get_artist_info(artist_id):
    return User().show(artist_id)

@app.route('/card/',methods = ['POST'])
def add_card():
    return Card().create()

@app.route('/subscription/',methods = ['POST'])
def subscribe():
    return User().subscribe()

@app.route('/comments/<song_id>',methods = ['POST'])
def add_comment(song_id):
    return Music().comment(song_id)

@app.route('/comments/<song_id>/<parent_comment_id>',methods = ['POST'])
def add_comment_reply(song_id,parent_comment_id):
    return Music().reply(song_id,parent_comment_id)

@app.route('/playlist/',methods = ['POST'])
def add_playlist():
    return User().create_playlist()

@app.route('/<song_id>/', methods = ['PUT'])
def listen(song_id):
    return Music().play_song(song_id)

@app.route('/report/')
def report():
    return Music().songs_played_per_month()



if __name__ == '__main__':
    # set up logging
    logging.basicConfig(filename='log_file.log')
    logger = logging.getLogger('logger')
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)

    # create formatter
    formatter = logging.Formatter('%(asctime)s [%(levelname)s]:  %(message)s', '%H:%M:%S')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    host = '127.0.0.1'
    port = 8080
    logger.info(f'API v1.0 online: http://{host}:{port}')
    app.run(host=host, debug=True, threaded=True, port=port)